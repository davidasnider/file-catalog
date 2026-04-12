import asyncio
import logging
from sqlmodel import select
from src.db.engine import init_db, async_session_maker
from src.db.models import Document, DocumentStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def backfill():
    await init_db()
    from src.db.fts import sync_document_to_fts

    async with async_session_maker() as session:
        result = await session.execute(
            select(Document).where(Document.status == DocumentStatus.COMPLETED)
        )
        docs = result.scalars().all()
        logger.info(f"Found {len(docs)} completed documents to sync to FTS.")

        for doc in docs:
            await sync_document_to_fts(session, doc.id)

        logger.info("FTS Sync complete.")


if __name__ == "__main__":
    asyncio.run(backfill())
