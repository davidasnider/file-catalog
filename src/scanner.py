import argparse
import asyncio
import hashlib
import logging
import os
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from src.db.engine import init_db, async_session_maker
from src.db.models import Document, DocumentStatus, AnalysisTask
from src.core.task_engine import TaskEngine
from src.core.file_type import detect_file_type
from src.plugin_registry import load_plugins

# Ensure plugins are loaded dynamically from the plugin registry
load_plugins()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def compute_file_hash(file_path: str, chunk_size: int = 8192) -> str:
    """Compute SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


async def ingest_directory(directory: str, session: AsyncSession):
    """Walk directory, compute hashes, and insert/update documents."""
    base_path = Path(directory)
    if not base_path.exists() or not base_path.is_dir():
        logger.error(f"Directory {directory} does not exist or is not a directory.")
        return []

    processed_doc_ids = []

    for root, _, files in os.walk(base_path):
        for filename in files:
            if filename.startswith("."):
                continue

            # Ensure file path is absolute to prevent duplicate DB identities
            file_path = str((Path(root) / filename).resolve())
            try:
                file_hash = compute_file_hash(file_path)
                mime_type = detect_file_type(file_path)

                # Check if document exists
                result = await session.execute(
                    select(Document).where(Document.path == file_path)
                )
                doc = result.scalar_one_or_none()

                if doc:
                    if doc.file_hash != file_hash:
                        logger.info(f"File modified: {file_path}. Resetting tasks.")
                        # File changed, delete old tasks and reset status
                        await session.execute(
                            AnalysisTask.__table__.delete().where(
                                AnalysisTask.document_id == doc.id
                            )
                        )
                        doc.file_hash = file_hash
                        doc.mime_type = mime_type
                        doc.status = DocumentStatus.PENDING
                        await session.commit()
                    processed_doc_ids.append(doc.id)
                else:
                    logger.info(f"New file found: {file_path}")
                    new_doc = Document(
                        path=file_path,
                        mime_type=mime_type,
                        file_hash=file_hash,
                        status=DocumentStatus.PENDING,
                    )
                    session.add(new_doc)
                    await session.commit()
                    await session.refresh(new_doc)
                    processed_doc_ids.append(new_doc.id)

            except Exception as e:
                logger.error(f"Error ingesting {file_path}: {e}")

    return processed_doc_ids


async def run_scanner(directory: str, max_concurrent: int = 5):
    """Main scanner logic."""
    await init_db()

    logger.info(f"Starting scan of directory: {directory}")

    async with async_session_maker() as session:
        # 1. Ingest files
        ingested_ids = await ingest_directory(directory, session)
        logger.info(f"Found {len(ingested_ids)} valid files in target directory.")

        if not ingested_ids:
            return

        # 2. Find all documents that need processing
        # We process any document that is not COMPLETED, OR if we force it through TaskEngine
        # so it can check versions on its own.
        # Since TaskEngine is so fast at skipping, we just pass all ingested local IDs to it.
        # This guarantees any updated plugin bumps will trigger successfully!

        docs_to_process = []
        result = await session.execute(
            select(Document).where(Document.id.in_(ingested_ids))
        )
        for doc in result.scalars().all():
            # Optimization: could check DB here if version bumps are needed, but TaskEngine does it.
            # We'll just append it.
            docs_to_process.append(doc.id)

    if not docs_to_process:
        logger.info("No documents to process.")
        return

    logger.info(f"Dispatching {len(docs_to_process)} documents to TaskEngine.")
    task_engine = TaskEngine(
        async_session_maker=async_session_maker,
        max_concurrent_tasks=max_concurrent,
    )

    # Process all concurrently via the engine's semaphore
    tasks = [task_engine.process_document(doc_id) for doc_id in docs_to_process]
    await asyncio.gather(*tasks)

    logger.info("Directory scan and analysis complete.")


def main():
    parser = argparse.ArgumentParser(
        description="Scan a directory and run LLM analysis pipeline."
    )
    parser.add_argument("directory", type=str, help="Path to the directory to scan.")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=2,
        help="Maximum number of concurrent documents to process.",
    )
    args = parser.parse_args()

    asyncio.run(run_scanner(args.directory, args.concurrency))


if __name__ == "__main__":
    main()
