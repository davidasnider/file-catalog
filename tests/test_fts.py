import pytest
import json
from sqlmodel import text
from src.db.models import Document, AnalysisTask, DocumentStatus, TaskStatus
from src.db.fts import sync_document_to_fts, search_fts
from src.core.analyzer_names import TEXT_EXTRACTOR_NAME


@pytest.fixture
async def fts_setup(db_session):
    """Ensure FTS virtual table exists for tests."""
    await db_session.execute(
        text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS document_fts USING fts5("
            "document_id UNINDEXED, "
            "path, "
            "content, "
            "summary"
            ");"
        )
    )
    yield db_session


@pytest.mark.asyncio
async def test_sync_document_to_fts(fts_setup):
    """Test that a completed document syncs its various plugin texts to FTS."""
    session = fts_setup

    # 1. Create a Document
    doc = Document(path="/test/fts/document.pdf", status=DocumentStatus.COMPLETED)
    session.add(doc)
    await session.commit()
    await session.refresh(doc)

    # 2. Add multiple completed tasks with different textual outputs
    tasks = [
        AnalysisTask(
            document_id=doc.id,
            task_name=TEXT_EXTRACTOR_NAME,
            status=TaskStatus.COMPLETED,
            result_data=json.dumps(
                {"text": "The quick brown fox jumps over the lazy dog."}
            ),
        ),
        AnalysisTask(
            document_id=doc.id,
            task_name="VisionAnalyzer",
            status=TaskStatus.COMPLETED,
            result_data=json.dumps({"description": "A photo of a brown fox."}),
        ),
        AnalysisTask(
            document_id=doc.id,
            task_name="Summarizer",
            status=TaskStatus.COMPLETED,
            result_data=json.dumps(
                {
                    "summary": "This document is primarily about a quick fox and a lazy dog."
                }
            ),
        ),
    ]
    session.add_all(tasks)
    await session.commit()

    # 3. Trigger FTS sync
    await sync_document_to_fts(session, doc.id)

    # 4. Verify FTS entry exists and contains aggregated data
    result = await session.execute(
        text("SELECT content, summary FROM document_fts WHERE document_id = :doc_id"),
        {"doc_id": doc.id},
    )
    row = result.fetchone()

    assert row is not None
    content, summary = row

    # Content should have both text and vision outputs
    assert "quick brown fox" in content
    assert "photo of a brown fox" in content

    # Summary should be extracted to the summary column
    assert "primarily about a quick fox" in summary


@pytest.mark.asyncio
async def test_search_fts(fts_setup):
    """Test phrase searching and snippet generation."""
    session = fts_setup

    doc = Document(path="/searchable/terms.txt", status=DocumentStatus.COMPLETED)
    session.add(doc)
    await session.commit()
    await session.refresh(doc)

    task = AnalysisTask(
        document_id=doc.id,
        task_name=TEXT_EXTRACTOR_NAME,
        status=TaskStatus.COMPLETED,
        result_data=json.dumps(
            {
                "text": "Hello world! This is a highly specific unique_searchable_term to find."
            }
        ),
    )
    session.add(task)
    await session.commit()

    await sync_document_to_fts(session, doc.id)

    # Search for the term
    results = await search_fts(session, "unique_searchable_term")

    assert len(results) == 1
    match = results[0]

    assert match["document_id"] == doc.id
    # Ensure highlight snippet is working
    assert "<b>unique_searchable_term</b>" in match["content_snippet"]


@pytest.mark.asyncio
async def test_search_fts_sanitization(fts_setup):
    """Test that punctuation and quotes don't break the SQLite parser."""
    session = fts_setup

    # Send a query with lots of unsafe punctuation and quotes
    # The new sanitization wraps in double quotes and escapes internal double quotes
    results = await search_fts(session, 'some "unsafe" query: with - punctuation!')

    # Should safely return empty rather than throwing a SQL syntax error
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_sync_pending_document_skipped(fts_setup):
    """Ensure we don't sync documents that haven't processed yet."""
    session = fts_setup

    doc = Document(path="/pending/file.txt", status=DocumentStatus.PENDING)
    session.add(doc)
    await session.commit()
    await session.refresh(doc)

    await sync_document_to_fts(session, doc.id)

    result = await session.execute(
        text("SELECT * FROM document_fts WHERE document_id = :doc_id"),
        {"doc_id": doc.id},
    )
    assert result.fetchone() is None


@pytest.mark.asyncio
async def test_sync_not_present_document_removes_from_fts(fts_setup):
    """Ensure documents marked as NOT_PRESENT are removed from the FTS index."""
    session = fts_setup

    # 1. Create a document and sync it to FTS
    doc = Document(path="/test/missing.txt", status=DocumentStatus.COMPLETED)
    session.add(doc)
    await session.commit()
    await session.refresh(doc)

    task = AnalysisTask(
        document_id=doc.id,
        task_name=TEXT_EXTRACTOR_NAME,
        status=TaskStatus.COMPLETED,
        result_data=json.dumps({"text": "Initial content to be indexed."}),
    )
    session.add(task)
    await session.commit()

    await sync_document_to_fts(session, doc.id)

    # Verify it is in FTS
    result = await session.execute(
        text("SELECT * FROM document_fts WHERE document_id = :doc_id"),
        {"doc_id": doc.id},
    )
    assert result.fetchone() is not None

    # 2. Mark as NOT_PRESENT and sync again
    doc.status = DocumentStatus.NOT_PRESENT
    await session.commit()

    await sync_document_to_fts(session, doc.id)

    # 3. Verify it is removed from FTS
    result = await session.execute(
        text("SELECT * FROM document_fts WHERE document_id = :doc_id"),
        {"doc_id": doc.id},
    )
    assert result.fetchone() is None
