import argparse
import asyncio
import logging
from typing import Optional
from sqlmodel import select
from src.db.engine import init_db, async_session_maker
from src.db.models import Document, AnalysisTask, DocumentStatus, TaskStatus

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def invalidate_tasks(
    task_filter: Optional[str] = None,
    error_filter: Optional[str] = None,
    mime_filter: Optional[str] = None,
    status_filter: str = "FAILED",
    dry_run: bool = False,
):
    """
    Find tasks matching filters and status, reset them to PENDING,
    and reset their parent documents to PENDING so they are re-scanned.
    """
    await init_db()

    # Map status string to TaskStatus enum
    target_status = (
        TaskStatus.COMPLETED if status_filter == "COMPLETED" else TaskStatus.FAILED
    )

    async with async_session_maker() as session:
        # Build query to select tasks and their documents
        query = (
            select(AnalysisTask, Document)
            .join(Document)
            .where(AnalysisTask.status == target_status)
        )

        if task_filter:
            query = query.where(AnalysisTask.task_name == task_filter)
            logger.info(f"Filtering by task name: {task_filter}")

        if error_filter:
            escaped = (
                error_filter.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            query = query.where(AnalysisTask.error_message.like(f"%{escaped}%"))
            logger.info(f"Filtering by error message containing: '{error_filter}'")

        if mime_filter:
            query = query.where(Document.mime_type.like(f"%{mime_filter}%"))
            logger.info(f"Filtering by MIME type: {mime_filter}")

        result = await session.execute(query)
        matching_records = result.all()

        if not matching_records:
            logger.info("No matching tasks found with the criteria.")
            return

        logger.info(
            f"Found {len(matching_records)} tasks to invalidate (Status: {status_filter})."
        )

        if dry_run:
            logger.info("[DRY RUN] Showing first 10 tasks that would be reset:")
            for i, (task, doc) in enumerate(matching_records[:10]):
                logger.info(
                    f"  - Doc ID {doc.id} ({doc.mime_type}): Task '{task.task_name}' -> Current Status: {task.status.value}"
                )
            logger.info(
                f"[DRY RUN] In total, {len(matching_records)} tasks and their parent documents would be reset to PENDING."
            )
            return

        # Perform invalidation
        reset_tasks_count = 0
        reset_docs_count = 0

        # We also need to gather parent document IDs to reset their status to PENDING
        doc_ids_to_reset = set()

        for task, doc in matching_records:
            task.status = TaskStatus.PENDING
            task.error_message = (
                f"Invalidated for rerun. Previous status was {status_filter}."
            )
            reset_tasks_count += 1
            doc_ids_to_reset.add(doc.id)

        # Commit task changes so they are flushed even if doc_ids_to_reset is empty
        await session.commit()

        # Batch update document status to PENDING
        doc_ids_list = list(doc_ids_to_reset)
        batch_size = 500
        for i in range(0, len(doc_ids_list), batch_size):
            batch = doc_ids_list[i : i + batch_size]
            doc_stmt = select(Document).where(Document.id.in_(batch))
            doc_result = await session.execute(doc_stmt)
            for doc in doc_result.scalars().all():
                # Only reset if currently FAILED or COMPLETED (we want them re-processed to handle the retried tasks)
                if doc.status in [DocumentStatus.FAILED, DocumentStatus.COMPLETED]:
                    doc.status = DocumentStatus.PENDING
                    reset_docs_count += 1

            # Commit periodically to keep transactions smaller
            await session.commit()

        logger.info(
            f"Successfully reset {reset_tasks_count} tasks and {reset_docs_count} documents to PENDING."
        )


def main():
    parser = argparse.ArgumentParser(
        description="Invalidate tasks in the database to retry them."
    )
    parser.add_argument(
        "--task", help="Filter by specific task name (e.g. EmailParser, Summarizer)"
    )
    parser.add_argument("--error", help="Filter by sub-string in error message")
    parser.add_argument(
        "--mime", help="Filter by MIME type prefix (e.g. 'message/rfc822')"
    )
    parser.add_argument(
        "--status",
        choices=["FAILED", "COMPLETED"],
        default="FAILED",
        help="Filter by task status to invalidate (default: FAILED)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print matching records without making changes",
    )

    args = parser.parse_args()

    asyncio.run(
        invalidate_tasks(
            task_filter=args.task,
            error_filter=args.error,
            mime_filter=args.mime,
            status_filter=args.status,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
