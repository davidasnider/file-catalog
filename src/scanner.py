import json
import argparse
import asyncio
import hashlib
import logging
import os
from pathlib import Path
from typing import Dict, List, Tuple
from sqlalchemy import func
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
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.columns import Columns

from src.db.engine import init_db, async_session_maker
from src.db.models import Document, DocumentStatus, AnalysisTask, TaskStatus
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
    ".xml",
    # Mailbox files should be exploded into individual .eml files first
    # using extract_and_cleanup_mbox.py before scanning.
    ".mbox",
    ".mbx",
    ".mbs",
    # Fonts
    ".ttf",
    ".otf",
    ".fon",
    ".woff",
    ".woff2",
    # Source Code
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cc",
    ".hh",
    ".java",
    ".go",
    ".rs",
    ".php",
    ".rb",
    ".m",
    ".mm",
}

IGNORED_MIME_TYPES = {
    "text/x-c",
    "text/xml",
    "application/xml",
    "application/xhtml+xml",
    "application/vnd.microsoft.portable-executable",
    "text/x-c++",
}


def has_ignored_extension(filename: str) -> bool:
    """Return True when any suffix in the filename should be ignored."""
    suffixes = Path(filename).suffixes
    return any(suffix.lower() in IGNORED_EXTENSIONS for suffix in suffixes)


# Ensure plugins are loaded dynamically from the plugin registry
plugin_dir = os.path.join(os.path.dirname(__file__), "plugins")
load_plugins(plugin_dir)

LOG_FILE = "scanner.log"


class CustomJsonFormatter(logging.Formatter):
    """Simple JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        import json
        from datetime import datetime

        log_record = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record)


def setup_logging(debug: bool = False):
    level = logging.DEBUG if debug else logging.INFO
    # Set logger levels for src packages
    logging.getLogger("src").setLevel(level)

    handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    if config.log_format == "json":
        handler.setFormatter(CustomJsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )

    logging.basicConfig(
        level=level,
        handlers=[handler],
        force=True,
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
    doc_queue: asyncio.Queue = None,
    queued_docs: set = None,
    id_to_path: dict = None,
    id_to_mime: dict = None,
    docs_to_process: list = None,
) -> Tuple[List[int], List[int]]:
    """
    Walk directory, compute hashes, and insert/update documents.

    Supports a producer-consumer model via doc_queue.

    Args:
        directory: Path to scan.
        session: DB session.
        progress: Rich Progress object.
        task_id: Rich Task ID for the ingestion bar.
        limit: Max files to ingest.
        mime_type_filter: Filter by MIME prefix.
        doc_queue: Queue to push discovered/updated doc IDs into.
        queued_docs: Set of IDs already in queue to prevent duplicates.
        id_to_path: Map of doc ID to path (updated for streaming).
        id_to_mime: Map of doc ID to MIME (updated for streaming).
        docs_to_process: List of doc IDs (updated for streaming).
    """
    base_path = Path(directory)
    if not base_path.exists() or not base_path.is_dir():
        if progress:
            progress.console.print(
                f"[bold red]Error: Directory {directory} does not exist or is not a directory.[/bold red]"
            )
        else:
            logger.error(f"Directory {directory} does not exist or is not a directory.")
        return [], []

    # 1. Bulk load existing document metadata for the target directory to avoid one-by-one queries
    if progress and task_id is not None:
        progress.update(
            task_id, description="[yellow]Loading existing document metadata..."
        )

    base_path_resolved = base_path.resolve()
    # Filter documents in DB by path prefix to avoid loading the entire database
    search_pattern = f"{base_path_resolved}%"
    result = await session.execute(
        select(Document).where(Document.path.like(search_pattern))
    )
    existing_docs: Dict[str, Document] = {
        doc.path: doc for doc in result.scalars().all()
    }

    # 2. Discover files
    if progress and task_id is not None:
        progress.update(task_id, description="[yellow]Discovering files...")

    seen_paths = set()

    def walk_disk():
        for root, _, files in os.walk(base_path):
            for filename in files:
                if filename.startswith("."):
                    continue
                if has_ignored_extension(filename):
                    continue
                file_path = str((Path(root) / filename).resolve())
                seen_paths.add(file_path)
                yield file_path

    # Discovery is now incremental via a generator
    files_on_disk = walk_disk()

    if progress and task_id is not None:
        # Initial description for walking/ingesting
        progress.update(
            task_id,
            total=None,
            description="[yellow]Discovering and ingesting files...",
        )

    processed_doc_ids = []
    # Temporary buffers for the current transaction batch (Copilot Fix: Atomic Sets)
    batch_processed_ids = []
    batch_queued_ids = []
    # Patience: use smaller batch size and yield often so workers get DB time
    batch_size = getattr(config, "ingest_batch_size", 25)
    pending_updates = 0
    batch_ids_to_queue = []

    for file_path in files_on_disk:
        try:
            # 3. Quick Metadata Check
            try:
                stat = await asyncio.to_thread(os.stat, file_path)
                file_size = stat.st_size
                mtime = stat.st_mtime
            except PermissionError as pe:
                logger.error(f"Permission denied accessing {file_path}: {pe}")
                if progress and task_id is not None:
                    progress.advance(task_id)
                continue
            except Exception as e:
                logger.error(f"Error stating {file_path}: {e}")
                if progress and task_id is not None:
                    progress.advance(task_id)
                continue

            doc = existing_docs.get(file_path)

            # FIX: Re-detect MIME type for .wma files misidentified as video.
            # This MUST run even for COMPLETED files to ensure they are correctly re-classified.
            current_mime = doc.mime_type if doc else None
            if file_path.lower().endswith(".wma") and (
                not current_mime or current_mime.startswith("video/")
            ):
                try:
                    current_mime = await asyncio.to_thread(detect_file_type, file_path)
                except PermissionError as pe:
                    logger.error(
                        f"Permission denied detecting type for {file_path}: {pe}"
                    )
                    if progress and task_id is not None:
                        progress.advance(task_id)
                    continue

                if doc and current_mime != doc.mime_type:
                    logger.info(
                        f"Correcting misidentified MIME type for {file_path}: {doc.mime_type} -> {current_mime}"
                    )
                    doc.mime_type = current_mime
                    # Track as updated to ensure commit
                    pending_updates += 1

            # 4. Content-based ingestion (only if needed)
            if not current_mime:
                try:
                    mime_type = await asyncio.to_thread(detect_file_type, file_path)
                except PermissionError as pe:
                    logger.error(
                        f"Permission denied detecting type for {file_path}: {pe}"
                    )
                    if progress and task_id is not None:
                        progress.advance(task_id)
                    continue
            else:
                mime_type = current_mime

            # Skip if MIME type is in the ignored list.
            # This handles both newly discovered files and existing files (ensuring consistency).
            if mime_type in IGNORED_MIME_TYPES:
                if progress and task_id is not None:
                    progress.advance(task_id)
                continue

            # Skip if metadata matches and status is COMPLETED
            if (
                doc
                and doc.file_size == file_size
                and doc.mtime == mtime
                and doc.status == DocumentStatus.COMPLETED
            ):
                # Even if completed, we must respect the filter
                if mime_type_filter and not (
                    mime_type and mime_type.startswith(mime_type_filter)
                ):
                    continue

                processed_doc_ids.append(doc.id)
                if progress and task_id is not None:
                    progress.advance(task_id)
                continue

            try:
                file_hash = await asyncio.to_thread(compute_file_hash, file_path)
            except PermissionError as pe:
                logger.error(f"Permission denied hashing {file_path}: {pe}")
                if progress and task_id is not None:
                    progress.advance(task_id)
                continue

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
                current_doc_id = doc.id
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
                current_doc_id = new_doc.id

            if (
                doc_queue is not None
                and queued_docs is not None
                and current_doc_id not in queued_docs
                and current_doc_id not in batch_queued_ids
            ):
                # Buffer IDs to queue only after commit to avoid workers missing docs
                batch_ids_to_queue.append((current_doc_id, file_path, mime_type))
                batch_queued_ids.append(current_doc_id)

            batch_processed_ids.append(current_doc_id)
            pending_updates += 1

            # Commit in batches to reduce SQLite locks and transaction overhead
            if pending_updates >= batch_size:
                await session.commit()
                # Now that commit is successful, finalize state and push to queue
                processed_doc_ids.extend(batch_processed_ids)
                if queued_docs is not None:
                    queued_docs.update(batch_queued_ids)

                for bid, path, mtype in batch_ids_to_queue:
                    if id_to_path is not None:
                        id_to_path[bid] = path
                    if id_to_mime is not None:
                        id_to_mime[bid] = mtype
                    if docs_to_process is not None:
                        docs_to_process.append(bid)
                    await doc_queue.put(bid)

                batch_ids_to_queue = []
                batch_processed_ids = []
                batch_queued_ids = []
                pending_updates = 0
                await asyncio.sleep(0.1)  # Patience: yield to worker tasks

        except Exception as e:
            from sqlalchemy.exc import SQLAlchemyError

            if isinstance(e, SQLAlchemyError):
                logger.exception(f"Database error during ingestion, rolling back: {e}")
                await session.rollback()
                # Reset buffers (Copilot Fix: Atomic Sets)
                batch_ids_to_queue = []
                batch_processed_ids = []
                batch_queued_ids = []
                pending_updates = 0
            else:
                logger.exception(f"Error ingesting {file_path}: {e}")

        if progress and task_id is not None:
            # We don't have a fixed total yet, so we just advance
            progress.advance(task_id)

        if (
            limit is not None
            and (len(processed_doc_ids) + len(batch_processed_ids)) >= limit
        ):
            break

    # Final commit for the last batch
    if pending_updates > 0 or batch_ids_to_queue:
        await session.commit()
        processed_doc_ids.extend(batch_processed_ids)
        if queued_docs is not None:
            queued_docs.update(batch_queued_ids)

        for bid, path, mtype in batch_ids_to_queue:
            if id_to_path is not None:
                id_to_path[bid] = path
            if id_to_mime is not None:
                id_to_mime[bid] = mtype
            if docs_to_process is not None:
                docs_to_process.append(bid)
            await doc_queue.put(bid)

    # 5. Final pass: Mark documents that exist in DB but are missing on disk
    # This only checks documents that are under the 'directory' being scanned.
    missing_count = 0
    missing_doc_ids = []
    processed_doc_ids_set = set(processed_doc_ids)

    for path, doc in existing_docs.items():
        if doc.id not in processed_doc_ids_set:
            try:
                # Ensure we compare against the resolved base path
                p = Path(path)
                if p.is_relative_to(base_path_resolved):
                    # Check against seen_paths first (O(1)), then verify with filesystem (O(disk))
                    # if limit or filters were used.
                    if path not in seen_paths:
                        exists = await asyncio.to_thread(os.path.exists, path)
                        if not exists:
                            if doc.status != DocumentStatus.NOT_PRESENT:
                                doc.status = DocumentStatus.NOT_PRESENT
                                missing_count += 1
                                missing_doc_ids.append(doc.id)
            except (ValueError, OSError):
                continue

    if missing_count > 0:
        logger.info(f"Marked {missing_count} missing files as NOT_PRESENT")
        await session.commit()

    return processed_doc_ids, missing_doc_ids


async def _load_and_queue_existing_docs(
    async_session_maker,
    docs_to_process,
    queued_docs,
    id_to_path,
    id_to_mime,
    doc_queue,
    mime_type_filter: str | None = None,
):
    """Helper to load non-COMPLETED docs from DB and queue those present on disk."""
    async with async_session_maker() as session:
        # Query with task counts to determine priority
        stmt = select(Document, func.count(AnalysisTask.id)).outerjoin(
            AnalysisTask, AnalysisTask.document_id == Document.id
        )

        # NOTE: We do NOT apply mime_type_filter in the SQL query here.
        # If we did, misclassified files (e.g. .wma stored as video/) would be
        # filtered out before they could reach the re-detection logic below.
        filters = [
            Document.status != DocumentStatus.COMPLETED,
            Document.status != DocumentStatus.NOT_PRESENT,
        ]

        stmt = stmt.where(*filters).group_by(Document.id)

        result = await session.execute(stmt)
        # Fetch all into memory to apply priority sorting
        docs_with_counts = list(result.all())

        def get_priority(item):
            doc, task_count = item
            # Priority 1: Zero processing (PENDING with no tasks)
            if doc.status == DocumentStatus.PENDING and task_count == 0:
                return 1
            # Priority 2: Failed files
            if doc.status == DocumentStatus.FAILED:
                return 2
            # Priority 3: Everything else (retries, resumed scans)
            return 3

        # Sort by priority, then by id for stable ordering
        docs_with_counts.sort(key=lambda x: (get_priority(x), x[0].id))

        missing_doc_ids = []
        for doc, _ in docs_with_counts:
            # Verify file still exists on disk before queueing
            if not os.path.exists(doc.path):
                logger.warning(
                    f"File missing on disk during startup, marking as NOT_PRESENT: {doc.path}"
                )
                doc.status = DocumentStatus.NOT_PRESENT
                missing_doc_ids.append(doc.id)
                continue

            # FIX: Re-detect MIME type for .wma files misidentified as video.
            # This MUST run before the MIME filter check below.
            mtype = doc.mime_type
            if doc.path.lower().endswith(".wma") and (
                not mtype or mtype.startswith("video/")
            ):
                mtype = detect_file_type(doc.path)
                if mtype != doc.mime_type:
                    logger.info(
                        f"Correcting misidentified MIME type for {doc.path}: {doc.mime_type} -> {mtype}"
                    )
                    doc.mime_type = mtype

            # Skip if MIME type is in the ignored list.
            if mtype in IGNORED_MIME_TYPES:
                continue

            # Apply MIME filter if provided
            if mime_type_filter and not (mtype and mtype.startswith(mime_type_filter)):
                continue

            docs_to_process.append(doc.id)
            queued_docs.add(doc.id)
            id_to_path[doc.id] = doc.path
            id_to_mime[doc.id] = mtype
            doc_queue.put_nowait(doc.id)

        if missing_doc_ids:
            from src.db.fts import remove_documents_from_fts

            try:
                await remove_documents_from_fts(session, missing_doc_ids)
            except Exception:
                logger.exception(
                    f"Failed to remove {len(missing_doc_ids)} missing docs from FTS"
                )
        await session.commit()



def _categorize_errors(result_data: str, missing_models: set, missing_libraries: set):
    """Helper to parse result_data and categorize specific missing dependencies."""
    if not result_data:
        return
    try:
        data = json.loads(result_data)
        err = data.get("error", "")
        if "model not found" in err.lower():
            missing_models.add(err)
        elif "llama-cpp-python is not installed" in err:
            missing_libraries.add(err)
    except Exception:
        pass

async def run_scanner(
    directory: str,
    max_concurrent: int,
    clean: bool,
    limit: int | None,
    mime_type_filter: str | None,
    limit_ratio: float,
):
    """Main scanner logic."""
    import time

    start_time = time.time()

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
        Layout(name="main", size=max_concurrent * 2 + 4),
        Layout(name="stats", size=16),
        Layout(name="bottom", size=10),
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
        from sqlalchemy import func

        stats_text = Text()
        async with async_session_maker() as session:
            # 1. Aggregate Document stats in one query
            doc_stats_res = await session.execute(
                select(Document.status, func.count(Document.id)).group_by(
                    Document.status
                )
            )
            doc_stats = {s: c for s, c in doc_stats_res.all()}
            total_docs = sum(doc_stats.values())
            completed_docs = doc_stats.get(DocumentStatus.COMPLETED, 0)
            failed_docs = doc_stats.get(DocumentStatus.FAILED, 0)
            finished_docs = completed_docs + failed_docs

            from sqlmodel import case

            # 2. Aggregate Task stats in one query (Group by Plugin and Status)
            task_stats_res = await session.execute(
                select(
                    AnalysisTask.task_name,
                    AnalysisTask.status,
                    case(
                        (AnalysisTask.result_data.like('%"skipped": true%'), True),
                        (AnalysisTask.result_data.like('%"skipped":true%'), True),
                        else_=False,
                    ).label("is_skipped"),
                    func.count(AnalysisTask.id).label("count"),
                ).group_by(
                    AnalysisTask.task_name,
                    AnalysisTask.status,
                    case(
                        (AnalysisTask.result_data.like('%"skipped": true%'), True),
                        (AnalysisTask.result_data.like('%"skipped":true%'), True),
                        else_=False,
                    ),
                )
            )

            plugin_stats = {}
            for t_name, t_status, is_skipped, t_count in task_stats_res.all():
                if t_name not in plugin_stats:
                    plugin_stats[t_name] = {
                        "total": 0,
                        "error": 0,
                        "skipped": 0,
                        "success": 0,
                        "results": [],
                    }

                s = plugin_stats[t_name]
                s["total"] += t_count

                status_str = (
                    t_status.name if hasattr(t_status, "name") else str(t_status)
                )
                if status_str == "FAILED" or status_str.endswith(".FAILED"):
                    s["error"] += t_count
                elif status_str == "COMPLETED" or status_str.endswith(".COMPLETED"):
                    if is_skipped:
                        s["skipped"] += t_count
                    else:
                        s["success"] += t_count

            # 3. Optional: Get a sample of errors for the error table (don't fetch all)
            error_counts = {}
            recent_errors = await session.execute(
                select(AnalysisTask.error_message)
                .where(AnalysisTask.status == TaskStatus.FAILED)
                .order_by(AnalysisTask.id.desc())
                .limit(100)  # Only look at last 100 errors for the summary
            )
            for (err_msg,) in recent_errors.all():
                if err_msg:
                    msg = err_msg.split(":")[0][:50]
                    error_counts[msg] = error_counts.get(msg, 0) + 1

            total_tasks = sum(s["total"] for s in plugin_stats.values())
            completed_tasks = sum(s["success"] for s in plugin_stats.values())
            failed_tasks = sum(s["error"] for s in plugin_stats.values())

            elapsed = time.time() - start_time
            if elapsed > 0 and finished_docs > 0:
                speed = finished_docs / elapsed
                speed_str = f"({speed:.1f} docs/sec)"
                remaining_docs = total_docs - finished_docs
                if remaining_docs > 0 and speed > 0:
                    eta_seconds = remaining_docs / speed
                    if eta_seconds > 86400:
                        from datetime import datetime, timedelta

                        eta_date = datetime.now() + timedelta(seconds=eta_seconds)
                        eta_str = (
                            f"ETA: {eta_date.strftime('%Y-%m-%d %H:%M')} {speed_str}"
                        )
                    else:
                        hours, rem = divmod(eta_seconds, 3600)
                        minutes, seconds = divmod(rem, 60)
                        eta_str = f"ETA: {int(hours):02}:{int(minutes):02}:{int(seconds):02}   {speed_str}"
                elif remaining_docs <= 0:
                    eta_str = "Status: Finishing..."
                else:
                    eta_str = "ETA: N/A"
            else:
                eta_str = "ETA: Calculating..."

            stats_text.append("📊 Global Status\n", style="bold white underline")
            stats_text.append(f"  Docs:   {finished_docs}/{total_docs}\n", style="cyan")
            stats_text.append(
                f"  Tasks:  {completed_tasks}/{total_tasks} ", style="blue"
            )
            stats_text.append(
                f"({failed_tasks} failed)\n",
                style="bold red" if failed_tasks > 0 else "dim",
            )

            hours, rem = divmod(elapsed, 3600)
            minutes, seconds = divmod(rem, 60)
            stats_text.append(
                f"  Uptime: {int(hours):02}:{int(minutes):02}:{int(seconds):02}   ",
                style="dim",
            )
            stats_text.append(f"{eta_str}", style="yellow")

            def plugin_sort_key(p):
                return (-plugin_stats[p]["error"], -plugin_stats[p]["total"], p)

            sorted_plugins = sorted(plugin_stats.keys(), key=plugin_sort_key)

            mid = (len(sorted_plugins) + 1) // 2
            left_plugins = sorted_plugins[:mid]
            right_plugins = sorted_plugins[mid:]

            def create_stats_table(plugins):
                tbl = Table(
                    box=None,
                    header_style="bold cyan",
                    padding=(0, 2),
                    expand=True,
                    show_header=True,
                    border_style="dim",
                )
                tbl.add_column("🔌 Plugin", style="bold white", ratio=2)
                tbl.add_column("Run", justify="right", style="dim", ratio=1)
                tbl.add_column("Skp", justify="right", style="yellow", ratio=1)
                tbl.add_column("Ok", justify="right", style="green", ratio=1)
                tbl.add_column("Err", justify="right", style="red", ratio=1)
                for plugin in plugins:
                    s = plugin_stats[plugin]
                    tbl.add_row(
                        plugin,
                        str(s["total"]),
                        str(s["skipped"]),
                        str(s["success"]),
                        str(s["error"]),
                    )
                return tbl

            plugins_columns = Columns(
                [create_stats_table(left_plugins), create_stats_table(right_plugins)],
                expand=True,
            )

            error_summary = Text()
            if error_counts:
                error_summary.append("❌ Top Errors\n", style="bold red underline")
                sorted_errors = sorted(
                    error_counts.items(), key=lambda x: x[1], reverse=True
                )[:5]
                for msg, count in sorted_errors:
                    error_summary.append(f"  {count}x: {msg[:45]}...", style="red")
                    if count != sorted_errors[-1][1] or msg != sorted_errors[-1][0]:
                        error_summary.append("\n")

            top_section = (
                Columns([stats_text, error_summary], expand=True)
                if error_counts
                else stats_text
            )
            plugins_title = Text("\n")

            group = Group(top_section, plugins_title, plugins_columns)

        return Panel(group, title="Scanner Intel", border_style="green")

    with Live(layout, console=console, refresh_per_second=4):
        progress.start()
        ingest_task = progress.add_task("[yellow]Ingesting files...", total=None)

        id_to_mime = {}

        doc_queue = asyncio.Queue()
        docs_to_process = []
        started_ids = set()
        queued_docs = set()
        id_to_path = {}

        # 1. Initial Startup: Load PENDING/FAILED documents from DB first
        # Extract to a function to handle detection logic cleanly
        await _load_and_queue_existing_docs(
            async_session_maker,
            docs_to_process,
            queued_docs,
            id_to_path,
            id_to_mime,
            doc_queue,
            mime_type_filter=mime_type_filter,
        )

        # Update total docs early for the progress bar
        total_docs = len(docs_to_process)
        overall_task = progress.add_task(
            "[cyan]Processing documents...", total=total_docs
        )

        # 0. Cleanup orphaned/stalled tasks from previous runs
        async with async_session_maker() as session:
            stalled_tasks_res = await session.execute(
                select(AnalysisTask).where(
                    AnalysisTask.status == TaskStatus.IN_PROGRESS
                )
            )
            stalled_tasks = stalled_tasks_res.scalars().all()
            if stalled_tasks:
                console.print(
                    f"[yellow]Found {len(stalled_tasks)} stalled tasks. Resetting to PENDING...[/yellow]"
                )
                for st in stalled_tasks:
                    st.status = TaskStatus.PENDING
                    st.error_message = "Stalled task reset on scanner startup."
                await session.commit()

            stalled_docs_res = await session.execute(
                select(Document).where(
                    Document.status.in_(
                        [DocumentStatus.EXTRACTING, DocumentStatus.ANALYZING]
                    )
                )
            )
            stalled_docs = stalled_docs_res.scalars().all()
            if stalled_docs:
                console.print(
                    f"[yellow]Found {len(stalled_docs)} stalled documents. Resetting to PENDING...[/yellow]"
                )
                for sd in stalled_docs:
                    sd.status = DocumentStatus.PENDING
                await session.commit()

        async def run_background_ingest():
            async with async_session_maker() as session:
                ingested_ids, missing_ids = await ingest_directory(
                    directory,
                    session,
                    progress,
                    ingest_task,
                    limit,
                    mime_type_filter,
                    doc_queue=doc_queue,
                    queued_docs=queued_docs,
                    id_to_path=id_to_path,
                    id_to_mime=id_to_mime,
                    docs_to_process=docs_to_process,
                )
                progress.update(
                    ingest_task,
                    description=f"[green]Ingestion complete! Found {len(ingested_ids)} files. ({len(missing_ids)} missing)",
                    completed=True,
                )

                # Sync missing files to FTS to ensure they are removed from search results
                if missing_ids:
                    from src.db.fts import remove_documents_from_fts

                    try:
                        await remove_documents_from_fts(session, missing_ids)
                    except Exception:
                        logger.exception(
                            f"Failed to remove {len(missing_ids)} missing docs from FTS"
                        )

        ingest_bg_task = asyncio.create_task(run_background_ingest())

        active_tasks = {}  # doc_id -> progress_task_id
        waiting_tasks = {}  # doc_id -> progress_task_id
        completed_count = 0
        missing_models = set()
        missing_libraries = set()
        processed_docs = set()

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

            # Keep total updated if ingest is streaming
            progress.update(overall_task, total=len(docs_to_process))

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

        post_process_semaphore = asyncio.Semaphore(max_concurrent + 1)

        async def check_doc_errors(doc_id):
            """Sync to FTS and check for specific runtime errors (like missing models)."""
            from src.db.fts import sync_document_to_fts

            async with post_process_semaphore:
                async with async_session_maker() as session:
                    # Sync to FTS index
                    try:
                        await sync_document_to_fts(session, doc_id)
                    except Exception as e:
                        logger.error(f"FTS sync failed for doc {doc_id}: {e}")

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

        abort_event = asyncio.Event()

        task_engine = TaskEngine(
            async_session_maker=async_session_maker,
            max_concurrent_tasks=max_concurrent,
            mime_limit_ratio=limit_ratio,
            callbacks={
                "doc_start": on_doc_start,
                "doc_end": on_doc_end,
                "plugin_start": on_plugin_start,
            },
            abort_event=abort_event,
        )

        loop = asyncio.get_running_loop()
        stop_requested = False

        def handle_sigint(*args):
            nonlocal stop_requested
            if stop_requested:
                console.print("\n[bold red]Forcing quit...[/bold red]")
                task_engine.request_abort()

                async def _force_quit():
                    await task_engine.notify_all()
                    current = asyncio.current_task()
                    for task in asyncio.all_tasks():
                        if task is not current and not task.done():
                            # We don't want to cancel the main task that is handling the shutdown
                            task.cancel()

                asyncio.create_task(_force_quit())
            else:
                stop_requested = True
                task_engine.request_abort()
                console.print(
                    "\n[bold yellow]Stop requested! Allowing active tasks to finish... Press Ctrl+C again to force quit.[/bold yellow]"
                )
                asyncio.create_task(task_engine.notify_all())

        import signal

        try:
            loop.add_signal_handler(signal.SIGINT, handle_sigint)
        except NotImplementedError:
            signal.signal(signal.SIGINT, handle_sigint)

        async def update_ui_panes():
            while True:
                # Update Log
                log_content = get_log_tail(8)
                layout["bottom"].update(
                    Panel(
                        Text.from_ansi(log_content, no_wrap=True),
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

        async def process_and_check(doc_id):
            if task_engine.abort_event and task_engine.abort_event.is_set():
                return
            mime_type = id_to_mime.get(doc_id)
            processed = await task_engine.process_document(doc_id, mime_type=mime_type)
            if processed:
                processed_docs.add(doc_id)
                try:
                    await check_doc_errors(doc_id)
                except Exception:
                    logger.exception(
                        "Post-processing check_doc_errors failed for document %s",
                        doc_id,
                    )

        async def worker():
            while True:
                doc_id = await doc_queue.get()
                if doc_id is None:  # Sentinel for shutdown
                    doc_queue.task_done()
                    break
                try:
                    await process_and_check(doc_id)
                finally:
                    doc_queue.task_done()

        # Start workers
        workers = [asyncio.create_task(worker()) for _ in range(max_concurrent)]

        try:
            # Wait for background ingest to finish streaming
            await ingest_bg_task
        except asyncio.CancelledError:
            # Re-raise cancellation to allow proper shutdown cleanup
            raise
        except Exception as e:
            logger.error(f"Background ingestion failed: {e}")
            # Cancel workers on failure to stop processing
            for w in workers:
                w.cancel()
        finally:
            # Send sentinels to tell any remaining workers to shut down
            for _ in range(max_concurrent):
                await doc_queue.put(None)

            # Wait for all workers to finish (allowing for cancellation/sentinels)
            await asyncio.gather(*workers, return_exceptions=True)

            import signal

            try:
                loop.remove_signal_handler(signal.SIGINT)
            except NotImplementedError:
                signal.signal(signal.SIGINT, signal.default_int_handler)

            progress.stop()
            ui_update_task.cancel()
            try:
                await ui_update_task
            except asyncio.CancelledError:
                pass

    # Let background tasks (like our check_doc_errors quick checks) settle
    await asyncio.sleep(0.1)

    console.print("\n[bold green]✨ Analysis Complete![/bold green]\n")

    if processed_docs:
        async with async_session_maker() as session:
            # Fetch errors only for documents processed in this run to avoid surfacing old errors.
            chunk_size = 900
            processed_list = list(processed_docs)
            for i in range(0, len(processed_list), chunk_size):
                chunk = processed_list[i : i + chunk_size]
                result = await session.execute(
                    select(AnalysisTask.result_data).where(
                        AnalysisTask.document_id.in_(chunk),
                        AnalysisTask.result_data.like('%"error"%'),
                    )
                )
                import json

                for result_data in result.scalars().all():
                    _categorize_errors(result_data, missing_models, missing_libraries)

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


async def run_standalone_judge():
    from src.db.engine import async_session_maker, init_db
    from src.db.models import AnalysisTask, Document, TaskStatus
    from src.core.judge import TaskJudge
    from src.core.config import config
    from sqlmodel import select
    from rich.console import Console
    from datetime import datetime, timezone
    import json

    # Force enable judge for standalone execution
    config.judge_enabled = True

    await init_db()

    console = Console()
    console.print("[bold cyan]Starting Standalone LLM Judge Evaluation...[/bold cyan]")
    judge = TaskJudge()

    async with async_session_maker() as session:
        # Get tasks that have result_data
        # Use more robust NULLS FIRST ordering for SQLite portability
        result = await session.execute(
            select(AnalysisTask, Document)
            .join(Document, AnalysisTask.document_id == Document.id)
            .where(AnalysisTask.status == TaskStatus.COMPLETED)
            .where(AnalysisTask.result_data.is_not(None))
            .where(AnalysisTask.result_data != "{}")
            .order_by(
                AnalysisTask.judged_at.is_(None).desc(), AnalysisTask.judged_at.asc()
            )
        )
        tasks_with_docs = result.all()

    if not tasks_with_docs:
        console.print(
            "[yellow]No completed tasks with result_data found in the database.[/yellow]"
        )
        return

    console.print(f"Found {len(tasks_with_docs)} tasks to evaluate.")

    # Pre-load all document contexts in a single query to avoid N+1
    doc_ids = list({doc.id for _, doc in tasks_with_docs})
    doc_contexts = {}
    async with async_session_maker() as session:
        chunk_size = 900
        for i in range(0, len(doc_ids), chunk_size):
            chunk = doc_ids[i : i + chunk_size]
            all_tasks_res = await session.execute(
                select(AnalysisTask).where(AnalysisTask.document_id.in_(chunk))
            )
            for t in all_tasks_res.scalars().all():
                if t.result_data:
                    try:
                        doc_contexts.setdefault(t.document_id, {})[t.task_name] = (
                            json.loads(t.result_data)
                        )
                    except Exception:
                        pass

    failed_count = 0
    passed_count = 0
    skipped_count = 0

    # Use a single session for all updates to improve performance
    async with async_session_maker() as session:
        for task, doc in tasks_with_docs:
            try:
                try:
                    result_data = json.loads(task.result_data)
                except Exception:
                    continue

                context = doc_contexts.get(doc.id, {})

                retry_count = 0
                max_retries = 1

                while retry_count <= max_retries:
                    console.print(
                        f"[dim]Evaluating {task.task_name} for Document {doc.path}...[/dim]",
                        end="\r",
                    )
                    status = await judge.judge_task(
                        task.task_name, doc.path, result_data, context
                    )

                    # Clear the line
                    console.print(" " * 120, end="\r")

                    if status == "PASSED":
                        if retry_count == 0:
                            passed_count += 1
                            console.print(
                                f"✅ [green]PASSED[/green] | Task: {task.task_name} | Doc: {doc.path}"
                            )
                        else:
                            passed_count += 1
                            console.print(
                                f"🎉 [green]FIXED ON RETRY[/green] | Task: {task.task_name} | Doc: {doc.path}"
                            )
                            # Save the fixed result to the database
                            from src.core.plugin_registry import ANALYZER_REGISTRY

                            analyzer_cls = ANALYZER_REGISTRY.get(task.task_name)
                            current_version = (
                                getattr(analyzer_cls, "_analyzer_version", None)
                                if analyzer_cls
                                else None
                            )
                            from src.db.fts import sync_document_to_fts

                            db_task = await session.get(AnalysisTask, task.id)
                            if db_task:
                                db_task.result_data = json.dumps(result_data)
                                db_task.status = TaskStatus.COMPLETED
                                db_task.error_message = None
                                db_task.updated_at = datetime.now(timezone.utc)
                                if current_version:
                                    db_task.plugin_version = current_version
                                await session.commit()
                                try:
                                    await sync_document_to_fts(session, doc.id)
                                    await session.commit()
                                except Exception as fts_err:
                                    logger.error(
                                        f"FTS resync failed during judge retry: {fts_err}"
                                    )
                        break
                    elif status == "SKIPPED":
                        skipped_count += 1
                        # We don't print skipped tasks to avoid spamming the console
                        break
                    elif status in ["ERROR", "FAILED"]:
                        if retry_count < max_retries:
                            console.print(
                                f"🔄 [yellow]FAILED/ERROR - Attempting Re-run ({retry_count + 1}/{max_retries})[/yellow] | Task: {task.task_name} | Doc: {doc.path}"
                            )
                            from src.core.plugin_registry import ANALYZER_REGISTRY

                            analyzer_cls = ANALYZER_REGISTRY.get(task.task_name)
                            if analyzer_cls:
                                try:
                                    analyzer = analyzer_cls()
                                    # Re-run the analyzer on the document
                                    result_data = await analyzer.analyze(
                                        doc.path, doc.mime_type, context
                                    )
                                    retry_count += 1
                                    continue  # Loop back and evaluate the new result
                                except Exception as e:
                                    console.print(
                                        f"[red]Retry execution failed:[/red] {e}"
                                    )
                            else:
                                console.print(
                                    f"[red]Cannot retry: Analyzer class {task.task_name} not found.[/red]"
                                )

                        # If we're here, retries were exhausted or the retry failed
                        if status == "ERROR":
                            failed_count += 1
                            console.print(
                                f"⚠️  [yellow]ERROR[/yellow]  | Task: {task.task_name} | Doc: {doc.path}"
                            )
                        else:
                            failed_count += 1

                        # The judge_task already printed the panel with details
                        try:
                            input(
                                "\nPress Enter to continue to the next evaluation (or Ctrl+C to quit)..."
                            )
                        except KeyboardInterrupt:
                            console.print(
                                "\n[bold red]Aborting evaluation...[/bold red]"
                            )
                            return
                        break

                # Record judged_at timestamp only for real verdicts (PASSED/SKIPPED/FAILED).
                # ERROR verdicts (system failures) don't update judged_at so they stay
                # at the front of the queue for the next run.
                if status in ["PASSED", "SKIPPED", "FAILED"]:
                    db_task = await session.get(AnalysisTask, task.id)
                    if db_task:
                        db_task.judged_at = datetime.now(timezone.utc)
                        # Commit incrementally to show progress in DB but keep the session open
                        await session.commit()
            except Exception as e:
                logger.error(
                    f"Unexpected error judging task {task.task_name} for {doc.path}: {e}"
                )
                console.print(
                    f"[bold red]Unexpected error judging {doc.path}:[/bold red] {e}"
                )
                continue

    console.print("\n[bold green]Evaluation Complete![/bold green]")
    console.print(f"Total Evaluated: {passed_count + failed_count + skipped_count}")
    console.print(f"Passed: [green]{passed_count}[/green]")
    console.print(f"Skipped: [dim]{skipped_count}[/dim] (Not eligible for judging)")
    console.print(f"Failed/Error: [red]{failed_count}[/red]")


def main():
    parser = argparse.ArgumentParser(
        description="Scan a directory and run LLM analysis pipeline."
    )
    parser.add_argument(
        "directory",
        type=str,
        nargs="?",
        default=None,
        help="Path to the directory to scan.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=config.max_concurrent,
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
        choices=["llama_cpp", "mlx", "gemini", "openai"],
        help="Provider for text generation models.",
    )
    parser.add_argument(
        "--vision-provider",
        type=str,
        default=config.vision_provider,
        choices=["llama_cpp", "mlx", "gemini", "openai"],
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
    parser.add_argument(
        "--log-format",
        type=str,
        default=config.log_format,
        choices=["standard", "json"],
        help="Format of the log output.",
    )
    parser.add_argument(
        "--judge",
        dest="run_judge",
        action="store_true",
        help="Run standalone LLM-as-a-Judge mode on completed tasks.",
    )
    parser.add_argument(
        "--concurrency-limit-ratio",
        type=float,
        default=config.concurrency_limit_ratio,
        help="Max percentage (0.0-1.0) of concurrency slots a single MIME group can occupy if others are waiting.",
    )

    args = parser.parse_args()

    # Update global config from CLI args before we run anything
    from src.core.config import update_config_from_cli

    # We remove mime_type from args before updating config because config doesn't have it
    args_dict = vars(args).copy()
    mime_type = args_dict.pop("mime_type", None)
    update_config_from_cli(**args_dict)

    setup_logging(args.debug)

    if args.run_judge:
        asyncio.run(run_standalone_judge())
    else:
        if not args.directory:
            print("Error: directory argument is required unless running --judge mode.")
            parser.print_help()
            import sys

            sys.exit(1)

        asyncio.run(
            run_scanner(
                args.directory,
                args.concurrency,
                args.clean,
                args.limit,
                mime_type,
                args.concurrency_limit_ratio,
            )
        )


if __name__ == "__main__":
    main()
