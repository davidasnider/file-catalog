import argparse
import asyncio
import json
import logging

from rich.console import Console
from rich.table import Table
from sqlmodel import select

from src.db.engine import async_session_maker
from src.db.models import Document, AnalysisTask, DocumentStatus, TaskStatus

# Set up logging early (or use the one from config)
logging.basicConfig(level=logging.WARNING)

logger = logging.getLogger(__name__)


async def report_failures(format="table", task_filter=None, ext_filter=None):
    """
    Generate a report of pipeline failures from the database.

    Args:
        format (str): Output format, either "table" (Rich) or "json".
        task_filter (str, optional): Name of a specific task to filter by.
        ext_filter (str, optional): File extension to filter by (e.g., ".pdf").
    """
    async with async_session_maker() as session:
        # Load all failed tasks and link them to their documents
        query = (
            select(AnalysisTask, Document)
            .join(Document)
            .where(AnalysisTask.status == TaskStatus.FAILED)
        )

        if task_filter:
            query = query.where(AnalysisTask.task_name == task_filter)

        result = await session.execute(query)
        failed_tasks = result.all()

        # Also get documents that are explicitly failed
        doc_query = select(Document).where(Document.status == DocumentStatus.FAILED)
        doc_result = await session.execute(doc_query)
        failed_docs = doc_result.scalars().all()

        failed_doc_ids_with_tasks = {task.document_id for task, doc in failed_tasks}

    failures = []

    for task, doc in failed_tasks:
        if ext_filter and not doc.path.lower().endswith(ext_filter.lower()):
            continue

        failures.append(
            {
                "type": "task",
                "document_id": doc.id,
                "path": doc.path,
                "mime_type": doc.mime_type,
                "task_name": task.task_name,
                "error_message": task.error_message or "Unknown error",
            }
        )

    for doc in failed_docs:
        if doc.id in failed_doc_ids_with_tasks:
            continue

        if ext_filter and not doc.path.lower().endswith(ext_filter.lower()):
            continue

        failures.append(
            {
                "type": "document",
                "document_id": doc.id,
                "path": doc.path,
                "mime_type": doc.mime_type,
                "task_name": "N/A",
                "error_message": "Document marked as FAILED (could be timeout, pipeline crash, etc.)",
            }
        )

    if format == "json":
        print(json.dumps(failures, indent=2))
        return

    console = Console()
    if not failures:
        console.print("[bold green]No failures found![/bold green]")
        return

    console.print(f"\n[bold red]Pipeline Failures: {len(failures)}[/bold red]\n")

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Doc ID", style="dim", width=6)
    table.add_column("Type/Task", style="cyan")
    table.add_column("MIME Type", style="blue")
    table.add_column("File", style="green", overflow="fold")
    table.add_column("Error", style="red")

    for f in failures:
        task_label = f["task_name"] if f["type"] == "task" else "Doc Error"

        # truncate path for display
        path = f["path"]
        if len(path) > 50:
            path = "..." + path[-47:]

        err = f.get("error_message", "")
        if isinstance(err, str):
            err = err.replace("\n", " ").strip()
            if len(err) > 80:
                err = err[:77] + "..."
        else:
            err = str(err)

        table.add_row(
            str(f["document_id"]), task_label, f["mime_type"] or "unknown", path, err
        )

    console.print(table)

    # Fetch global stats for the summary table
    async with async_session_maker() as session:
        from sqlalchemy import func

        # Query: count(id), status, mime_type GROUP BY status, mime_type
        stats_query = select(
            Document.status, Document.mime_type, func.count(Document.id)
        ).group_by(Document.status, Document.mime_type)
        stats_result = await session.execute(stats_query)
        raw_stats = stats_result.all()

    # Aggregate stats: {mime: {"FAILED": X, "COMPLETED": Y, "PENDING": Z}}
    from collections import defaultdict

    summary_stats = defaultdict(lambda: {"FAILED": 0, "COMPLETED": 0, "PENDING": 0})

    for status, mime, count in raw_stats:
        m = mime or "unknown"
        s = status.name if hasattr(status, "name") else str(status)
        if s in ["FAILED", "COMPLETED", "PENDING"]:
            summary_stats[m][s] = count
        elif s in ["ANALYZING", "EXTRACTING"]:
            summary_stats[m]["PENDING"] += (
                count  # Treat in-progress as pending for this view
            )

    # Ensure anything that failed in tasks but not doc status is counted in FAILED for the summary
    for f in failures:
        summary_stats[f["mime_type"] or "unknown"]["FAILED"] = max(
            summary_stats[f["mime_type"] or "unknown"]["FAILED"], 1
        )  # Just ensures it's at least 1 if we have a failure record

    # Sort by frequency of FAILED descending
    sorted_mimes = sorted(
        summary_stats.items(), key=lambda x: x[1]["FAILED"], reverse=True
    )

    summary_table = Table(
        title="\nSummary by MIME Type", show_header=True, header_style="bold cyan"
    )
    summary_table.add_column("MIME Type", style="blue")
    summary_table.add_column("Failed", justify="right", style="bold red")
    summary_table.add_column("Succeeded", justify="right", style="green")
    summary_table.add_column("Pending", justify="right", style="dim yellow")

    for mime, counts in sorted_mimes:
        if counts["FAILED"] > 0 or counts["COMPLETED"] > 0 or counts["PENDING"] > 0:
            summary_table.add_row(
                mime,
                str(counts["FAILED"]),
                str(counts["COMPLETED"]),
                str(counts["PENDING"]),
            )

    console.print(summary_table)


def main():
    parser = argparse.ArgumentParser(description="Report pipeline failures")
    parser.add_argument(
        "--format", choices=["table", "json"], default="table", help="Output format"
    )
    parser.add_argument(
        "--task", help="Filter by specific task name (e.g. TextExtractor)"
    )
    parser.add_argument("--ext", help="Filter by file extension (e.g. .pdf)")

    args = parser.parse_args()

    asyncio.run(
        report_failures(format=args.format, task_filter=args.task, ext_filter=args.ext)
    )


if __name__ == "__main__":
    main()
