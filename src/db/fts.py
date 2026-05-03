import json
import logging
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from src.db.models import DocumentStatus, TaskStatus
from src.core.analyzer_names import (
    TEXT_EXTRACTOR_NAME,
    DOCUMENT_AI_EXTRACTOR_NAME,
    AUDIO_TRANSCRIBER_NAME,
    VISION_ANALYZER_NAME,
    VIDEO_ANALYZER_NAME,
    EMAIL_PARSER_NAME,
    SPREADSHEET_ANALYZER_NAME,
    SUMMARIZER_NAME,
)

logger = logging.getLogger(__name__)

# Global semaphore to serialize FTS writes and prevent "database is locked" errors.
# SQLite allows multiple concurrent readers but only one writer.
# Because FTS (Full Text Search) indexing is write-intensive and involves complex virtual tables,
# we use this semaphore to ensure only one document is being synced to FTS at a time across
# all concurrent analysis workers.
_fts_semaphore = None


def get_fts_semaphore():
    global _fts_semaphore
    if _fts_semaphore is None:
        _fts_semaphore = asyncio.Semaphore(1)
    return _fts_semaphore


async def sync_document_to_fts(session: AsyncSession, document_id: int):
    """
    Sync a completed document and its analysis tasks into the FTS5 virtual table
    for full-text search.
    """
    # Fetch the document to ensure it exists and get its path
    result = await session.execute(
        text("SELECT path, status FROM document WHERE id = :doc_id"),
        {"doc_id": document_id},
    )
    doc = result.fetchone()

    if not doc:
        logger.warning(f"Cannot sync document {document_id} to FTS: not found")
        return

    path, status = doc

    # If the document is missing from the filesystem, remove it from the search index
    if status == DocumentStatus.NOT_PRESENT:
        async with get_fts_semaphore():
            await session.execute(
                text("DELETE FROM document_fts WHERE rowid = :doc_id"),
                {"doc_id": document_id},
            )
            await session.commit()
        logger.info(f"Removed missing document {document_id} from FTS")
        return

    # We only want to index documents that have attempted processing
    if status in (DocumentStatus.PENDING, DocumentStatus.EXTRACTING):
        return

    # Fetch all COMPLETED tasks for this document to build the FTS content
    tasks_result = await session.execute(
        text(
            "SELECT task_name, result_data FROM analysistask WHERE document_id = :doc_id AND status = :status"
        ),
        {"doc_id": document_id, "status": TaskStatus.COMPLETED.value},
    )
    tasks = tasks_result.fetchall()

    content_parts = []
    summary_text = ""

    for task_name, result_data_str in tasks:
        if not result_data_str:
            continue

        try:
            data = json.loads(result_data_str)
        except json.JSONDecodeError:
            continue

        normalized_task_name = task_name.lower()

        # Extract textual content based on the task type
        if (
            task_name == TEXT_EXTRACTOR_NAME
            or normalized_task_name == TEXT_EXTRACTOR_NAME.lower()
            or normalized_task_name == "text_extractor"
        ):
            if text_content := data.get("text"):
                content_parts.append(text_content)

        elif (
            task_name == DOCUMENT_AI_EXTRACTOR_NAME
            or normalized_task_name == "document_ai_extractor"
        ):
            if text_content := data.get("text"):
                content_parts.append(text_content)

        elif (
            task_name == AUDIO_TRANSCRIBER_NAME
            or normalized_task_name == "audio_transcriber"
        ):
            if text_content := data.get("text"):
                content_parts.append(text_content)

        elif (
            task_name == VISION_ANALYZER_NAME
            or normalized_task_name == "vision_analyzer"
        ):
            if description := data.get("description"):
                content_parts.append(description)

        elif (
            task_name == VIDEO_ANALYZER_NAME or normalized_task_name == "video_analyzer"
        ):
            if description := data.get("visual_description"):
                content_parts.append(description)

        elif task_name == EMAIL_PARSER_NAME or normalized_task_name == "email_parser":
            if subject := data.get("subject"):
                content_parts.append(f"Subject: {subject}")
            if text_content := data.get("text_body"):
                content_parts.append(text_content)

        elif (
            task_name == SPREADSHEET_ANALYZER_NAME
            or normalized_task_name == "spreadsheet_analyzer"
        ):
            if text_content := data.get("raw_text_content"):
                content_parts.append(text_content)
            elif summary := data.get("summary"):
                content_parts.append(summary)

        elif task_name == SUMMARIZER_NAME or normalized_task_name == "summarizer":
            if summary := data.get("summary"):
                summary_text = summary

    # Combine all extracted content into a single searchable body
    full_content = "\n\n".join(content_parts)

    # Use the global semaphore to ensure only one FTS write happens at a time.
    # While the scanner manages this globally, keeping the lock here provides
    # "safety by default" for other callers (like scripts or web UI updates).
    async with get_fts_semaphore():
        # Execute the two statements (delete old, insert new) separately

        # 1. Delete existing entry if it exists
        await session.execute(
            text("DELETE FROM document_fts WHERE rowid = :doc_id"),
            {"doc_id": document_id},
        )

        # 2. Insert new entry
        await session.execute(
            text(
                "INSERT INTO document_fts(rowid, document_id, path, content, summary) "
                "VALUES(:doc_id, :doc_id, :path, :content, :summary)"
            ),
            {
                "doc_id": document_id,
                "path": path,
                "content": full_content,
                "summary": summary_text,
            },
        )

        await session.commit()
    logger.info(f"Synced document {document_id} to FTS")


async def search_fts(session: AsyncSession, query: str, limit: int = 50):
    """
    Search the FTS5 table and return results with snippets.
    """
    if not query or not query.strip():
        return []

    search_sql = """
        SELECT
            document_id,
            path,
            snippet(document_fts, 2, '<b>', '</b>', '...', 64) as content_snippet,
            snippet(document_fts, 3, '<b>', '</b>', '...', 64) as summary_snippet,
            rank
        FROM document_fts
        WHERE document_fts MATCH :query
        ORDER BY rank
        LIMIT :limit
    """

    # SQLite FTS syntax: wrap queries in quotes to do phrase search and avoid syntax errors
    # on punctuation. We escape internal double quotes by doubling them.
    safe_query = f'"{query.replace(chr(34), chr(34) * 2)}"'

    try:
        result = await session.execute(
            text(search_sql), {"query": safe_query, "limit": limit}
        )
        return [dict(row._mapping) for row in result.fetchall()]
    except Exception as e:
        logger.error(f"FTS search failed for query '{query}': {e}")
        return []
