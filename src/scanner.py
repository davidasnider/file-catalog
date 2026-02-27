import argparse
import asyncio
import hashlib
import logging
import os
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeElapsedColumn,
)
from rich.console import Console

from src.db.engine import init_db, async_session_maker
from src.db.models import Document, DocumentStatus, AnalysisTask
from src.core.task_engine import TaskEngine
from src.core.file_type import detect_file_type
from src.core.plugin_registry import load_plugins

# Ensure plugins are loaded dynamically from the plugin registry
plugin_dir = os.path.join(os.path.dirname(__file__), "plugins")
load_plugins(plugin_dir)

# Set logger levels for src packages to WARNING so standard INFO logs don't clutter the rich UI
logging.getLogger("src").setLevel(logging.WARNING)

logging.basicConfig(
    level=logging.WARNING, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def compute_file_hash(file_path: str, chunk_size: int = 8192) -> str:
    """Compute SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


async def ingest_directory(
    directory: str,
    session: AsyncSession,
    progress: Progress = None,
    task_id=None,
    limit: int = None,
) -> list[int]:
    """Walk directory, compute hashes, and insert/update documents."""
    base_path = Path(directory)
    if not base_path.exists() or not base_path.is_dir():
        if progress:
            progress.console.print(
                f"[bold red]Error: Directory {directory} does not exist or is not a directory.[/bold red]"
            )
        else:
            logger.error(f"Directory {directory} does not exist or is not a directory.")
        return []

    processed_doc_ids = []

    files_to_process = []
    for root, _, files in os.walk(base_path):
        for filename in files:
            if filename.startswith("."):
                continue
            files_to_process.append(str((Path(root) / filename).resolve()))

    if limit is not None:
        files_to_process = files_to_process[:limit]

    if progress and task_id is not None:
        progress.update(task_id, total=len(files_to_process))

    for file_path in files_to_process:
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
                    # File changed, delete old tasks and reset status using session to maintain SQLAlchemy cache consistency
                    await session.execute(
                        AnalysisTask.__table__.delete().where(
                            AnalysisTask.document_id == doc.id
                        )
                    )
                    doc.file_hash = file_hash
                    doc.mime_type = mime_type
                    doc.status = DocumentStatus.PENDING
                    await session.commit()
                    await session.refresh(doc)
                processed_doc_ids.append(doc.id)
            else:
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

        if progress and task_id is not None:
            progress.advance(task_id)

    return processed_doc_ids


async def run_scanner(
    directory: str, max_concurrent: int = 5, clean: bool = False, limit: int = None
):
    """Main scanner logic."""
    if clean:
        console = Console()
        console.print("[yellow]Cleaning database...[/yellow]")
        from src.db.engine import engine
        from sqlmodel import SQLModel

        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)

    await init_db()

    console = Console()
    console.print(
        f"\n[bold blue]🚀 File Catalog Scanner[/bold blue]\n[dim]Scanning directory:[/dim] [green]{directory}[/green]\n"
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        ingest_task = progress.add_task("[yellow]Ingesting files...", total=None)

        async with async_session_maker() as session:
            # 1. Ingest files
            ingested_ids = await ingest_directory(
                directory, session, progress, ingest_task, limit
            )
            progress.update(
                ingest_task,
                description=f"[green]Ingestion complete! Found {len(ingested_ids)} valid files.",
                completed=True,
            )

            if not ingested_ids:
                return

            docs_to_process = []
            result = await session.execute(
                select(Document).where(Document.id.in_(ingested_ids))
            )
            for doc in result.scalars().all():
                docs_to_process.append(doc.id)

        if not docs_to_process:
            console.print("[yellow]No documents to process.")
            return

        overall_task = progress.add_task(
            "[cyan]Processing documents...", total=len(docs_to_process)
        )

        active_tasks = {}
        missing_models = set()
        missing_libraries = set()

        def on_doc_start(doc_id):
            active_tasks[doc_id] = progress.add_task(
                f"  [dim]Doc {doc_id}...[/dim]", total=None
            )

        def on_plugin_start(doc_id, plugin_name):
            task_id = active_tasks.get(doc_id)
            if task_id is not None:
                progress.update(
                    task_id,
                    description=f"  [magenta]Doc {doc_id}:[/magenta] {plugin_name}",
                )

        def on_doc_end(doc_id):
            task_id = active_tasks.get(doc_id)
            if task_id is not None:
                progress.remove_task(task_id)
                try:
                    del active_tasks[doc_id]
                except KeyError:
                    pass
            progress.advance(overall_task)

            # Briefly check the DB to see if any tasks on this doc failed due to missing LLM dependencies
            # We do this quickly to aggregate the end-of-run warning
            async def check_doc_errors():
                async with async_session_maker() as session:
                    result = await session.execute(
                        select(AnalysisTask).where(AnalysisTask.document_id == doc_id)
                    )
                    import json

                    for t in result.scalars().all():
                        if t.result_data:
                            try:
                                data = json.loads(t.result_data)
                                err = data.get("error", "")
                                if "Llama model not found" in err:
                                    missing_models.add(err)
                                elif "llama-cpp-python is not installed" in err:
                                    missing_libraries.add(err)
                            except Exception:
                                pass

            # Fire-and-forget the check
            asyncio.create_task(check_doc_errors())

        callbacks = {
            "doc_start": on_doc_start,
            "plugin_start": on_plugin_start,
            "doc_end": on_doc_end,
        }

        task_engine = TaskEngine(
            async_session_maker=async_session_maker,
            max_concurrent_tasks=max_concurrent,
            callbacks=callbacks,
        )

        tasks = [task_engine.process_document(doc_id) for doc_id in docs_to_process]
        await asyncio.gather(*tasks)

    # Let background tasks (like our check_doc_errors quick checks) settle
    await asyncio.sleep(0.1)

    console.print("\n[bold green]✨ Analysis Complete![/bold green]\n")

    if missing_models or missing_libraries:
        console.print(
            "[bold yellow]⚠️  Notice: Local LLMs were skipped for some tasks.[/bold yellow]"
        )
        for model_err in missing_models:
            console.print(f"  [dim]- {model_err}[/dim]")
        for lib_err in missing_libraries:
            console.print(f"  [dim]- {lib_err}[/dim]")
        console.print(
            "[dim]  (Documents successfully ingested, but summaries and estate analysis were skipped. "
            "Install models or dependencies to enable full processing next run.)[/dim]\n"
        )


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
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean the database before scanning.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of files to process.",
    )
    args = parser.parse_args()

    asyncio.run(run_scanner(args.directory, args.concurrency, args.clean, args.limit))


if __name__ == "__main__":
    main()
