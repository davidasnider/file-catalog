import asyncio
import logging
from sqlalchemy import func
from sqlmodel import select, delete
from src.db.engine import init_db, async_session_maker
from src.db.models import Document, AnalysisTask
from src.db.fts import remove_documents_from_fts

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def cleanup():
    """Find and remove all XML-related documents and tasks from the database."""
    await init_db()
    async with async_session_maker() as session:
        # Query for documents that are either .xml files (case-insensitive) or have XML MIME types
        statement = select(Document).where(
            (func.lower(Document.path).like("%.xml"))
            | (
                Document.mime_type.in_(
                    ["text/xml", "application/xml", "application/xhtml+xml"]
                )
            )
        )
        result = await session.execute(statement)
        docs = result.scalars().all()

        if not docs:
            logger.info("No XML documents found in the database.")
            return

        doc_ids = [doc.id for doc in docs if doc.id is not None]
        logger.info(
            f"Removing {len(doc_ids)} XML documents and their associated data (tasks, FTS)."
        )

        # Delete in batches to avoid SQLite parameter limits (max 999, using 500 for safety)
        batch_size = 500
        for i in range(0, len(doc_ids), batch_size):
            batch = doc_ids[i : i + batch_size]

            # 1. Remove from Full-Text Search (FTS) first
            # We fail fast here to ensure we don't leave orphaned FTS entries
            try:
                await remove_documents_from_fts(session, batch)
                logger.debug(f"Removed batch of {len(batch)} from FTS index.")
            except Exception as e:
                logger.error(f"CRITICAL: Failed to remove documents from FTS: {e}")
                logger.error("Aborting to maintain database consistency.")
                await session.rollback()
                return

            # 2. Delete AnalysisTasks associated with these documents
            task_delete_statement = delete(AnalysisTask).where(
                AnalysisTask.document_id.in_(batch)
            )
            await session.execute(task_delete_statement)

            # 3. Delete the Document records
            doc_delete_statement = delete(Document).where(Document.id.in_(batch))
            await session.execute(doc_delete_statement)

            logger.info(f"Deleted batch of {len(batch)} documents.")

        await session.commit()
        logger.info("Database cleanup for XML files complete.")


if __name__ == "__main__":
    asyncio.run(cleanup())
