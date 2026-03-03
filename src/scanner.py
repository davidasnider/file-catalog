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

# Set logger levels for src packages to WARNING so standard INFO logs don't clutter the rich UI
logging.getLogger("src").setLevel(logging.WARNING)

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("scanner.log", encoding="utf-8"),
        logging.StreamHandler(),
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

            # Ignore structural or developer noise files based on extension
            _, ext = os.path.splitext(filename)
            if ext.lower() in IGNORED_EXTENSIONS:
                continue

            files_to_process.append(str((Path(root) / filename).resolve()))

    if progress and task_id is not None:
        progress.update(task_id, total=len(files_to_process))

    for file_path in files_to_process:
        try:
            mime_type = detect_file_type(file_path)

            if mime_type_filter and not (
                mime_type and mime_type.startswith(mime_type_filter)
            ):
                if progress and task_id is not None:
                    progress.advance(task_id)
                continue

            file_hash = compute_file_hash(file_path)

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

        if limit is not None and len(processed_doc_ids) >= limit:
            break

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
        from src.llm.llama_cpp import LlamaCppProvider, HAS_HF_HUB
        from src.core.config import config

        if HAS_HF_HUB and not os.path.exists(config.llm_model_path):
            console.print(
                "[yellow]⬇️  Downloading Local LLM (Llama-3-8B). This may take a few minutes...[/yellow]"
            )
            LlamaCppProvider.download_model(config.llm_model_path)
            console.print("[green]✅ Download complete![/green]\n")
    except ImportError:
        pass

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
                directory, session, progress, ingest_task, limit, mime_type_filter
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
    # New Arguments for LLM / Vision / Document AI
    parser.add_argument(
        "--llm-provider",
        type=str,
        default="llama_cpp",
        choices=["llama_cpp", "mlx", "gemini"],
        help="Provider for text generation models.",
    )
    parser.add_argument(
        "--vision-provider",
        type=str,
        default="llama_cpp",
        choices=["llama_cpp", "mlx", "gemini"],
        help="Provider for vision models.",
    )
    parser.add_argument(
        "--use-cloud-fallback",
        action="store_true",
        help="Allow falling back to cloud providers (e.g. Gemini) if local models fail.",
    )
    parser.add_argument(
        "--use-document-ai",
        action="store_true",
        help="Use Google Cloud Document AI for text extraction in PDFs/Images instead of local tools.",
    )
    parser.add_argument(
        "--llm-model-path",
        type=str,
        default="models/Llama-3-8B.gguf",
        help="Path or name of the text LLM model.",
    )
    parser.add_argument(
        "--vision-model-path",
        type=str,
        default="models/Llava-1.5-7b-ggml-model-q4_k.gguf",
        help="Path or name of the vision LLM model.",
    )
    parser.add_argument(
        "--mime-type",
        type=str,
        default=None,
        help="Filter ingestion to only documents matching this MIME type (e.g. 'image/jpeg' or 'image/').",
    )

    args = parser.parse_args()

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
