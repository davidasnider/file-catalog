import asyncio
import logging
from sqlalchemy import func, text, bindparam
from sqlmodel import select, delete
from src.db.engine import init_db, async_session_maker
from src.db.models import Document, AnalysisTask
from src.db.fts import get_fts_semaphore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def cleanup():
    """Find and remove all XML-related documents and tasks from the database."""
    await init_db()
    async with async_session_maker() as session:
        # Query only Document IDs to save memory (case-insensitive path match)
        statement = select(Document.id).where(
            (func.lower(Document.path).like("%.xml"))
            | (
                Document.mime_type.in_(
                    ["text/xml", "application/xml", "application/xhtml+xml"]
                )
            )
        )
        result = await session.execute(statement)
        doc_ids = result.scalars().all()

        if not doc_ids:
            logger.info("No XML documents found in the database.")
            return

        logger.info(
            f"Removing {len(doc_ids)} XML documents and their associated data (tasks, FTS)."
        )

        # Delete in batches to avoid SQLite parameter limits (max 999, using 500 for safety)
        batch_size = 500
        for i in range(0, len(doc_ids), batch_size):
            batch = doc_ids[i : i + batch_size]

            try:
                # 1. Remove from Full-Text Search (FTS) first
                # We reimplement the delete inline to avoid the internal commit in src.db.fts.remove_documents_from_fts
                async with get_fts_semaphore():
                    await session.execute(
                        text(
                            "DELETE FROM document_fts WHERE rowid IN :doc_ids"
                        ).bindparams(bindparam("doc_ids", expanding=True)),
                        {"doc_ids": list(batch)},
                    )

                # 2. Delete AnalysisTasks associated with these documents
                task_delete_statement = delete(AnalysisTask).where(
                    AnalysisTask.document_id.in_(batch)
                )
                await session.execute(task_delete_statement)

                # 3. Delete the Document records
                doc_delete_statement = delete(Document).where(Document.id.in_(batch))
                await session.execute(doc_delete_statement)

                # 4. Commit the entire batch atomically
                await session.commit()
                logger.info(f"Successfully deleted batch of {len(batch)} documents.")

            except Exception as e:
                logger.error(
                    f"CRITICAL: Failed to process batch starting at index {i}: {e}"
                )
                logger.error(
                    "Rolling back current batch to maintain database consistency."
                )
                await session.rollback()
                # We continue to the next batch instead of aborting the whole script,
                # but since FTS/Task/Doc deletes are now in one transaction, the DB remains consistent.

        logger.info("Database cleanup for XML files complete.")


if __name__ == "__main__":
    asyncio.run(cleanup())
