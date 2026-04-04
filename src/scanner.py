import argparse
import asyncio
import hashlib
import logging
import os
from pathlib import Path
from typing import Dict, List
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
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.table import Table

from src.db.engine import init_db, async_session_maker
from src.db.models import Document, DocumentStatus, AnalysisTask
from src.core.task_engine import TaskEngine
from src.core.file_type import detect_file_type
from src.core.plugin_registry import load_plugins
from src.core.config import config

# Add global constants for noise files
IGNORED_EXTENSIONS = {
    ".css",
    ".js",
    ".py",
    ".pyc",
    ".html_part",
    ".sh",
    ".ts",
    ".map",
    ".jsx",
    ".tsx",
}

# Ensure plugins are loaded dynamically from the plugin registry
plugin_dir = os.path.join(os.path.dirname(__file__), "plugins")
load_plugins(plugin_dir)

LOG_FILE = "scanner.log"


def setup_logging(debug: bool = False):
    level = logging.DEBUG if debug else logging.INFO
    # Set logger levels for src packages
    logging.getLogger("src").setLevel(level)

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
        ],
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
    mime_type_filter: str = None,
) -> List[int]:
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

    # 1. Bulk load existing document metadata to avoid one-by-one queries
    if progress and task_id is not None:
        progress.update(
            task_id, description="[yellow]Loading existing document metadata..."
        )

    result = await session.execute(select(Document))
    existing_docs: Dict[str, Document] = {
        doc.path: doc for doc in result.scalars().all()
    }

    # 2. Discover files
    if progress and task_id is not None:
        progress.update(task_id, description="[yellow]Discovering files...")

    files_on_disk = []

    def walk_disk():
        found = []
        for root, _, files in os.walk(base_path):
            for filename in files:
                if filename.startswith("."):
                    continue
                _, ext = os.path.splitext(filename)
                if ext.lower() in IGNORED_EXTENSIONS:
                    continue
                found.append(str((Path(root) / filename).resolve()))
        return found

    files_on_disk = await asyncio.to_thread(walk_disk)

    if progress and task_id is not None:
        total_files = (
            len(files_on_disk) if limit is None else min(limit, len(files_on_disk))
        )
        progress.update(
            task_id, total=total_files, description="[yellow]Ingesting files..."
        )

    processed_doc_ids = []
    batch_size = 100
    pending_updates = 0

    for file_path in files_on_disk:
        try:
            # 3. Quick Metadata Check
            stat = await asyncio.to_thread(os.stat, file_path)
            file_size = stat.st_size
            mtime = stat.st_mtime

            doc = existing_docs.get(file_path)

            # Skip if metadata matches and status is COMPLETED
            if (
                doc
                and doc.file_size == file_size
                and doc.mtime == mtime
                and doc.status == DocumentStatus.COMPLETED
            ):
                processed_doc_ids.append(doc.id)
                if progress and task_id is not None:
                    progress.advance(task_id)
                continue

            # 4. Content-based ingestion (only if needed)
            mime_type = await asyncio.to_thread(detect_file_type, file_path)

            if mime_type_filter and not (
                mime_type and mime_type.startswith(mime_type_filter)
            ):
                if progress and task_id is not None:
                    progress.advance(task_id)
                continue

            file_hash = await asyncio.to_thread(compute_file_hash, file_path)

            if doc:
                # Document exists, check if hash changed or we just need to update metadata
                if doc.file_hash != file_hash:
                    # Content changed: reset tasks and status
                    from src.db.models import AnalysisTask

                    await session.execute(
                        AnalysisTask.__table__.delete().where(
                            AnalysisTask.document_id == doc.id
                        )
                    )
                    doc.file_hash = file_hash
                    doc.status = DocumentStatus.PENDING

                doc.mime_type = mime_type
                doc.file_size = file_size
                doc.mtime = mtime
                processed_doc_ids.append(doc.id)
            else:
                # New document
                new_doc = Document(
                    path=file_path,
                    mime_type=mime_type,
                    file_hash=file_hash,
                    file_size=file_size,
                    mtime=mtime,
                    status=DocumentStatus.PENDING,
                )
                session.add(new_doc)
                # Flush the session to get the ID but don't commit yet to avoid overhead
                await session.flush()
                processed_doc_ids.append(new_doc.id)

            pending_updates += 1

            # Commit in batches to reduce SQLite locks and transaction overhead
            if pending_updates >= batch_size:
                await session.commit()
                pending_updates = 0

        except Exception as e:
            logger.error(f"Error ingesting {file_path}: {e}")

        if progress and task_id is not None:
            progress.advance(task_id)

        if limit is not None and len(processed_doc_ids) >= limit:
            break

    # Final commit for the last batch
    if pending_updates > 0:
        await session.commit()

    return processed_doc_ids


async def run_scanner(
    directory: str,
    max_concurrent: int = 5,
    clean: bool = False,
    limit: int = None,
    mime_type_filter: str = None,
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

    # 0. Pre-flight checks: Ensure LLM models are downloaded before hijacking the console with Rich Progress
    try:
        from src.core.config import config

        if config.llm_provider == "llama_cpp":
            from src.llm.llama_cpp import LlamaCppProvider, HAS_HF_HUB

            if HAS_HF_HUB and not os.path.exists(config.llm_model_path):
                console.print(
                    f"[yellow]⬇️  Downloading Local LLM ({config.llm_display_name}). This may take a few minutes...[/yellow]"
                )
                try:
                    LlamaCppProvider.download_model(config.llm_model_path)
                    console.print("[green]✅ Download complete![/green]\n")
                except FileNotFoundError:
                    console.print(
                        f"[yellow]⚠️  Could not auto-download model at {config.llm_model_path}. Skipping.[/yellow]\n"
                    )
    except ImportError:
        pass

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=None),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        expand=True,
    )

    layout = Layout()
    layout.split_column(
        Layout(name="top", ratio=3),
        Layout(name="bottom", ratio=2),
    )
    layout["top"].split_row(
        Layout(name="main", ratio=2),
        Layout(name="stats", ratio=1),
    )
    layout["bottom"].update(
        Panel(
            Text("Initializing log tail..."),
            title="scanner.log (tail)",
            border_style="blue",
        )
    )
    layout["main"].update(
        Panel(
            progress,
            title="Scanning Status",
            border_style="cyan",
        )
    )

    def get_log_tail(n=10):
        if not os.path.exists(LOG_FILE):
            return ""
        try:
            # Efficiently read only the last n lines of the log file without
            # loading the entire file into memory on each UI refresh.
            block_size = 1024
            newline = b"\n"
            with open(LOG_FILE, "rb") as f:
                f.seek(0, os.SEEK_END)
                file_size = f.tell()
                if file_size == 0:
                    return ""

                data = b""
                lines_found = 0
                # Read backwards in chunks until we have enough newlines or hit BOF.
                while file_size > 0 and lines_found <= n:
                    read_size = min(block_size, file_size)
                    file_size -= read_size
                    f.seek(file_size)
                    chunk = f.read(read_size)
                    if not chunk:
                        break
                    data = chunk + data
                    lines_found = data.count(newline)
                    if file_size == 0:
                        break

                # Split into lines and take the last n.
                tail_lines = data.splitlines()[-n:]
                return "\n".join(
                    line.decode("utf-8", errors="replace") for line in tail_lines
                )
        except Exception:
            return "Error reading log file."

    async def get_stats():
        import json
        from sqlalchemy import func

        stats_text = Text()
        async with async_session_maker() as session:
            # Query document counts with aggregate functions
            total_docs = await session.scalar(select(func.count(Document.id))) or 0
            completed_docs = (
                await session.scalar(
                    select(func.count(Document.id)).where(
                        Document.status == DocumentStatus.COMPLETED
                    )
                )
                or 0
            )

            # Query aggregated task counts by status
            task_counts_result = await session.execute(
                select(
                    AnalysisTask.status,
                    func.count().label("count"),
                ).group_by(AnalysisTask.status)
            )
            status_counts = {}
            for status, count in task_counts_result.all():
                status_key = status.name if hasattr(status, "name") else str(status)
                status_counts[status_key] = status_counts.get(status_key, 0) + (
                    count or 0
                )

            total_tasks = sum(status_counts.values())
            completed_tasks = status_counts.get("COMPLETED", 0)
            failed_tasks = status_counts.get("FAILED", 0)

            stats_text.append("📊 Global Status\n", style="bold white underline")
            stats_text.append(f"  Docs:  {completed_docs}/{total_docs}\n", style="cyan")
            stats_text.append(
                f"  Tasks: {completed_tasks}/{total_tasks} ", style="blue"
            )
            stats_text.append(
                f"({failed_tasks} failed)\n\n",
                style="bold red" if failed_tasks > 0 else "dim",
            )

            # Query only necessary columns for the plugin table
            task_result = await session.execute(
                select(
                    AnalysisTask.task_name,
                    AnalysisTask.status,
                    AnalysisTask.error_message,
                    AnalysisTask.result_data,
                )
            )
            all_tasks = task_result.all()

            # plugin_name -> {total: X, error: Y, skipped: Z, success: W, results: []}
            plugin_stats = {}
            error_counts = {}  # error_msg -> count

            for t in all_tasks:
                if t.task_name not in plugin_stats:
                    plugin_stats[t.task_name] = {
                        "total": 0,
                        "error": 0,
                        "skipped": 0,
                        "success": 0,
                        "results": [],
                    }

                s = plugin_stats[t.task_name]
                s["total"] += 1

                # Check status via string or name attribute
                status_str = (
                    t.status.name if hasattr(t.status, "name") else str(t.status)
                )

                if status_str == "FAILED":
                    s["error"] += 1
                    if t.error_message:
                        # Truncate and clean up error message for aggregation
                        msg = t.error_message.split(":")[0][:50]
                        error_counts[msg] = error_counts.get(msg, 0) + 1
                elif status_str == "COMPLETED":
                    if t.result_data:
                        try:
                            data = json.loads(t.result_data)
                            is_skipped = (
                                data.get("skipped") is True
                                or data.get("reason")
                                == "Condition not met by should_run"
                            )

                            if is_skipped:
                                s["skipped"] += 1
                            else:
                                s["success"] += 1
                                s["results"].append(data)
                        except Exception:
                            s["success"] += 1
                    else:
                        s["success"] += 1

            # Build Plugins Table
            table = Table(
                box=None,
                header_style="bold white",
                padding=(0, 1),
                expand=True,
                show_header=True,
                border_style="dim",
            )
            table.add_column("Plugin", style="bold white", ratio=2)
            table.add_column("Run", justify="right", style="dim", ratio=1)
            table.add_column("Skp", justify="right", style="yellow", ratio=1)
            table.add_column("Ok", justify="right", style="green", ratio=1)
            table.add_column("Err", justify="right", style="red", ratio=1)

            sorted_plugins = sorted(plugin_stats.keys())
            for plugin in sorted_plugins:
                s = plugin_stats[plugin]
                table.add_row(
                    plugin,
                    str(s["total"]),
                    str(s["skipped"]),
                    str(s["success"]),
                    str(s["error"]),
                )

            # Re-assemble the text with the table in the middle
            output_text = Text()
            output_text.append(stats_text)
            output_text.append("\n🔌 Plugins\n", style="bold white underline")

            # Combine everything into a Group or just use a Renderable list
            from rich.console import Group

            error_summary = Text()
            if error_counts:
                error_summary.append("\n❌ Top Errors\n", style="bold red underline")
                sorted_errors = sorted(
                    error_counts.items(), key=lambda x: x[1], reverse=True
                )[:3]
                for msg, count in sorted_errors:
                    error_summary.append(f"  {count}x: {msg[:30]}...\n", style="red")

            group = Group(stats_text, table, error_summary)

        return Panel(group, title="Scanner Intel", border_style="green")

    with Live(layout, console=console, refresh_per_second=4):
        progress.start()
        ingest_task = progress.add_task("[yellow]Ingesting files...", total=None)

        async with async_session_maker() as session:
            # 1. Ingest files
            ingested_ids = await ingest_directory(
                directory, session, progress, ingest_task, limit, mime_type_filter
            )
            progress.update(
                ingest_task,
                description=f"[green]Ingestion complete! Found {len(ingested_ids)} valid files.",
                completed=True,
            )

            if not ingested_ids:
                return

            # Fetch paths for all ingested IDs to show "waiting" status
            result = await session.execute(
                select(Document.id, Document.path).where(Document.id.in_(ingested_ids))
            )
            id_to_path = {row[0]: row[1] for row in result.all()}
            docs_to_process = ingested_ids

        if not docs_to_process:
            console.print("[yellow]No documents to process.")
            return

        total_docs = len(docs_to_process)
        overall_task = progress.add_task(
            "[cyan]Processing documents...", total=total_docs
        )

        active_tasks = {}  # doc_id -> progress_task_id
        waiting_tasks = {}  # doc_id -> progress_task_id
        started_ids = set()
        completed_count = 0
        missing_models = set()
        missing_libraries = set()

        def update_waiting():
            nonlocal waiting_tasks
            # Clear all current waiting tasks to ensure they stay at the bottom
            for did in list(waiting_tasks.keys()):
                progress.remove_task(waiting_tasks[did])
            waiting_tasks = {}

            # Find next N that haven't started
            next_waiting = []
            for doc_id in docs_to_process:
                if doc_id not in started_ids:
                    next_waiting.append(doc_id)
                    if len(next_waiting) >= max_concurrent:
                        break

            # Add them back
            for did in next_waiting:
                path = id_to_path.get(did, f"Doc {did}")
                filename = os.path.basename(path)
                waiting_tasks[did] = progress.add_task(
                    f"  [dim]Waiting: {filename}[/dim]", total=None
                )

        update_waiting()

        def on_doc_start(doc_id, path=None, mime_type=None):
            started_ids.add(doc_id)
            # Remove from waiting if it was there
            if doc_id in waiting_tasks:
                progress.remove_task(waiting_tasks[doc_id])
                del waiting_tasks[doc_id]

            filename = os.path.basename(path) if path else f"Doc {doc_id}"
            active_tasks[doc_id] = progress.add_task(
                f"  [dim]{filename}[/dim]",
                total=None,
            )
            update_waiting()

        def on_plugin_start(doc_id, plugin_name, path=None, mime_type=None):
            task_id = active_tasks.get(doc_id)
            if task_id is not None:
                filename = os.path.basename(path) if path else f"Doc {doc_id}"
                progress.update(
                    task_id,
                    description=f"  [magenta]{filename}:[/magenta] {plugin_name}",
                )

        def on_doc_end(doc_id):
            nonlocal completed_count
            task_id = active_tasks.get(doc_id)
            if task_id is not None:
                progress.remove_task(task_id)
                try:
                    del active_tasks[doc_id]
                except KeyError:
                    pass

            completed_count += 1
            progress.update(
                overall_task,
                description="[cyan]Processing documents...",
                completed=completed_count,
            )
            update_waiting()

            # Briefly check the DB to see if any tasks on this doc failed due to missing LLM dependencies
            # We do this quickly to aggregate the end-of-run warning
            async def check_doc_errors():
                from src.db.fts import sync_document_to_fts

                async with async_session_maker() as session:
                    # Sync to FTS index
                    try:
                        await sync_document_to_fts(session, doc_id)
                    except Exception as e:
                        logger.error(f"FTS sync failed for doc {doc_id}: {e}")

                    result = await session.execute(
                        select(AnalysisTask).where(AnalysisTask.document_id == doc_id)
                    )
                    import json

                    for t in result.scalars().all():
                        if t.result_data:
                            try:
                                data = json.loads(t.result_data)
                                err = data.get("error", "")
                                if "model not found" in err.lower():
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

        # Background task to update the log pane and stats pane
        async def update_ui_panes():
            while True:
                # Update Log
                log_content = get_log_tail(12)
                layout["bottom"].update(
                    Panel(
                        Text.from_ansi(log_content),
                        title="scanner.log (tail)",
                        border_style="blue",
                    )
                )

                # Update Stats
                try:
                    stats_panel = await get_stats()
                    layout["stats"].update(stats_panel)
                except Exception as e:
                    logger.error(f"Error updating stats UI: {e}")

                await asyncio.sleep(1.0)

        ui_update_task = asyncio.create_task(update_ui_panes())

        tasks = [task_engine.process_document(doc_id) for doc_id in docs_to_process]
        try:
            await asyncio.gather(*tasks)
        finally:
            progress.stop()
            ui_update_task.cancel()
            try:
                await ui_update_task
            except asyncio.CancelledError:
                pass

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
        default=4,
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
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging.",
    )
    # New Arguments for LLM / Vision / Document AI
    parser.add_argument(
        "--llm-provider",
        type=str,
        default=config.llm_provider,
        choices=["llama_cpp", "mlx", "gemini"],
        help="Provider for text generation models.",
    )
    parser.add_argument(
        "--vision-provider",
        type=str,
        default=config.vision_provider,
        choices=["llama_cpp", "mlx", "gemini"],
        help="Provider for vision models.",
    )
    parser.add_argument(
        "--use-cloud-fallback",
        action=argparse.BooleanOptionalAction,
        default=config.use_cloud_fallback,
        help="Allow falling back to cloud providers (e.g. Gemini) if local models fail.",
    )
    parser.add_argument(
        "--use-document-ai",
        action=argparse.BooleanOptionalAction,
        default=config.use_document_ai,
        help="Use Google Cloud Document AI for text extraction in PDFs/Images instead of local tools.",
    )
    parser.add_argument(
        "--llm-model-path",
        type=str,
        default=config.llm_model_path,
        help="Path or name of the text LLM model.",
    )
    parser.add_argument(
        "--vision-model-path",
        type=str,
        default=config.vision_model_path,
        help="Path or name of the vision LLM model.",
    )
    parser.add_argument(
        "--mime-type",
        type=str,
        default=None,
        help="Filter ingestion to only documents matching this MIME type (e.g. 'image/jpeg' or 'image/').",
    )

    args = parser.parse_args()

    setup_logging(args.debug)

    # Update global config from CLI args before we run anything
    from src.core.config import update_config_from_cli

    # We remove mime_type from args before updating config because config doesn't have it
    args_dict = vars(args).copy()
    mime_type = args_dict.pop("mime_type", None)
    update_config_from_cli(**args_dict)

    asyncio.run(
        run_scanner(args.directory, args.concurrency, args.clean, args.limit, mime_type)
    )


if __name__ == "__main__":
    main()
