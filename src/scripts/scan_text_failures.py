import argparse
import asyncio
import os
from pathlib import Path
from collections import defaultdict

from rich.console import Console
from rich.table import Table
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
)

from src.core.file_type import detect_file_type
from src.plugins.text_extractor import TextExtractorPlugin


async def scan_directory_for_failures(directory: str, limit: int = None):
    console = Console()
    base_path = Path(directory)

    if not base_path.exists() or not base_path.is_dir():
        console.print(
            f"[bold red]Error: {directory} is not a valid directory.[/bold red]"
        )
        return

    console.print("\n[bold blue]🔍 Text Extraction Failure Scanner[/bold blue]")
    console.print(f"[dim]Scanning directory:[/dim] [green]{directory}[/green]\n")

    files_to_scan = []
    for root, _, files in os.walk(base_path):
        for filename in files:
            if filename.startswith("."):
                continue
            files_to_scan.append(str((Path(root) / filename).resolve()))

    if limit is not None:
        files_to_scan = files_to_scan[:limit]

    extractor = TextExtractorPlugin()

    # Track statistics
    total_files = len(files_to_scan)
    success_count = 0
    failure_counts = defaultdict(int)  # mime_type -> count

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        scan_task = progress.add_task("[yellow]Scanning files...", total=total_files)

        for file_path in files_to_scan:
            mime_type = detect_file_type(file_path)

            # Fast-fail for known non-text binaries that we don't have extractors for yet
            # (If it's supported, TextExtractor should handle it. If it fails or skips, it's a failure)

            try:
                # We mock a small context since TextExtractor doesn't strictly need one
                result = await extractor.analyze(file_path, mime_type, {})

                if result.get("extracted") and bool(result.get("text", "").strip()):
                    success_count += 1
                else:
                    # Extractor ran but returned no text (e.g., unsupported mime type)
                    failure_counts[mime_type] += 1
            except Exception:
                # Extractor threw an error
                failure_counts[mime_type] += 1

            progress.advance(scan_task)

    # Print Results
    console.print("\n[bold green]✅ Scan Complete![/bold green]")
    console.print(f"Total Files: {total_files}")
    console.print(f"Successfully Extracted: {success_count}")
    console.print(f"Failed / Unsupported: {total_files - success_count}\n")

    if failure_counts:
        table = Table(title="Top Missing Extractors by MIME Type")
        table.add_column("MIME Type", style="cyan", no_wrap=True)
        table.add_column("Failure Count", style="magenta", justify="right")

        # Sort by count descending
        sorted_failures = sorted(
            failure_counts.items(), key=lambda x: x[1], reverse=True
        )

        for mime, count in sorted_failures:
            table.add_row(mime, str(count))

        console.print(table)
        console.print(
            "\n[dim]Use this list to prioritize adding new extractors (e.g. Video, Audio, Archives).[/dim]\n"
        )
    else:
        console.print(
            "[bold green]All files were successfully extracted![/bold green]\n"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Scan a directory to identify files that fail text extraction."
    )
    parser.add_argument("directory", type=str, help="Path to the directory to scan.")
    parser.add_argument(
        "--limit", type=int, default=None, help="Limit number of files to scan."
    )

    args = parser.parse_args()
    asyncio.run(scan_directory_for_failures(args.directory, args.limit))


if __name__ == "__main__":
    main()
