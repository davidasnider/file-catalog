import argparse
import asyncio
import json
import os
import sys
import base64
import datetime
from pathlib import Path
from typing import Dict, Any, Optional

import yaml
from sqlalchemy import select

from src.db.engine import async_session_maker, init_db
from src.db.models import Document, AnalysisTask
from src.plugins.video_analyzer import VideoAnalyzerPlugin

# Rich library components for terminal beautification
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

# Initialize console
console = Console()


def display_image_iterm2(file_path: str):
    """Displays an image in iTerm2 using its inline image protocol."""
    if not os.path.exists(file_path):
        return

    with open(file_path, "rb") as f:
        image_data = f.read()

    b64_data = base64.b64encode(image_data).decode("ascii")

    # iTerm2 protocol: ESC ] 1337 ; File = [args] : [base64 data] ^G
    sys.stdout.write(
        f"\033]1337;File=name={base64.b64encode(file_path.encode()).decode()};inline=1;width=40%:{b64_data}\a\n"
    )
    sys.stdout.flush()


def format_size(bytes_size: Optional[int]) -> str:
    """Format file size in human-readable units."""
    if bytes_size is None:
        return "Unknown"
    size = float(bytes_size)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} TB"


def format_mtime(mtime: Optional[float]) -> str:
    """Format POSIX modification time to string."""
    if mtime is None:
        return "Unknown"
    try:
        dt = datetime.datetime.fromtimestamp(mtime, tz=datetime.timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return "Unknown"


def format_pii_value(val: Any) -> str:
    """Formats complex PII dictionary/list objects into clean readable strings."""
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        if "city" in val or "state" in val or "zip_code" in val:
            parts = []
            street = val.get("street_address") or ""
            if street:
                parts.append(street)
            mailing = val.get("mailing_address")
            if isinstance(mailing, dict):
                box_num = mailing.get("box_number")
                if box_num:
                    parts.append(f"PO Box {box_num}")
            city = val.get("city") or ""
            state = val.get("state") or ""
            zip_c = val.get("zip_code") or ""
            city_state_zip = f"{city}, {state} {zip_c}".strip(", ")
            if city_state_zip:
                parts.append(city_state_zip)
            return " / ".join(parts) if parts else str(val)
        return ", ".join(f"{k}: {v}" for k, v in val.items())
    return str(val)


def print_rich_analysis(info: Dict[str, Any]):
    """Renders the document metadata and analysis using Rich library component panels and tables."""
    doc = info["document"]
    results = info["analysis_results"]

    # 1. Header Banner
    console.print()
    console.print(
        Panel(
            Text.assemble(
                ("🔍 Document Inspection: ", "bold cyan"),
                (os.path.basename(doc["path"]), "bold white"),
            ),
            box=box.ROUNDED,
            border_style="cyan",
            subtitle="Local AI File Catalog Pipeline",
            subtitle_align="right",
        )
    )

    # 2. General Document Metadata
    meta_table = Table(box=box.SIMPLE, show_header=False, border_style="dim blue")
    meta_table.add_column("Property", style="bold cyan", width=22)
    meta_table.add_column("Value", style="white")

    meta_table.add_row("Database Record ID", f"#{doc['id']}")
    meta_table.add_row("Absolute File Path", doc["path"])

    # Status Coloring
    status = doc["status"]
    status_style = "bold yellow"
    if status == "COMPLETED":
        status_style = "bold green"
    elif status == "FAILED":
        status_style = "bold red"
    elif status == "ANALYZING":
        status_style = "bold magenta"

    meta_table.add_row(
        "Processing Status", f"[{status_style}]{status}[/{status_style}]"
    )
    meta_table.add_row("MIME Type", doc["mime_type"] or "Unknown")
    meta_table.add_row("File Size", format_size(doc["file_size"]))
    meta_table.add_row("Modification Time", format_mtime(doc["mtime"]))
    meta_table.add_row("Registered In Catalog", doc["created_at"] or "Unknown")

    # SHA-256 Hash
    dup_data = results.get("DuplicateDetector", {}).get("data", {})
    file_hash = (
        doc.get("file_hash") or dup_data.get("file_hash") or "Not calculated yet"
    )
    meta_table.add_row("SHA-256 Content Hash", file_hash)

    console.print(
        Panel(
            meta_table,
            title="[bold white]📄 File Metadata[/bold white]",
            border_style="blue",
            box=box.ROUNDED,
        )
    )

    # 3. Categorization & Language
    router_data = results.get("Router", {}).get("data", {})
    lang_data = results.get("LanguageDetector", {}).get("data", {})

    cat = router_data.get("category", "Unknown")
    cat_style = "bold white"
    if cat == "Legal/Estate":
        cat_style = "bold magenta"
    elif cat == "Financial":
        cat_style = "bold green"
    elif cat == "Technical":
        cat_style = "bold cyan"
    elif cat == "Image":
        cat_style = "bold yellow"
    elif cat in ("Video", "Audio"):
        cat_style = "bold bright_blue"

    lang_name = lang_data.get("language_name", "Unknown")
    lang_conf = lang_data.get("confidence", 0.0)
    lang_str = (
        f"{lang_name} ({lang_conf * 100:.1f}% confidence)"
        if lang_name != "Unknown"
        else "Unknown"
    )

    class_table = Table(box=box.SIMPLE, show_header=False, border_style="dim magenta")
    class_table.add_column("Property", style="bold magenta", width=22)
    class_table.add_column("Value", style="white")
    class_table.add_row(
        "Taxonomy Category",
        f"[{cat_style}]{cat}[/{cat_style}] (routed via {router_data.get('method', 'heuristic')})",
    )
    class_table.add_row("Language Detected", lang_str)

    console.print(
        Panel(
            class_table,
            title="[bold white]🏷️ Taxonomy & Identification[/bold white]",
            border_style="magenta",
            box=box.ROUNDED,
        )
    )

    # 4. Summary & Deep Summary
    sum_data = results.get("Summarizer", {}).get("data", {})
    deep_sum_data = results.get("DeepSummarizer", {}).get("data", {})

    summary_text = (
        sum_data.get("summary")
        or deep_sum_data.get("extensive_summary")
        or deep_sum_data.get("summary")
    )
    summary_source = (
        "DeepSummarizer (Map-Reduce)"
        if deep_sum_data.get("extensive_summary")
        else ("Summarizer" if sum_data.get("summary") else None)
    )

    if summary_text:
        console.print(
            Panel(
                Text(summary_text, style="italic white"),
                title=f"[bold white]📝 Document Summary ({summary_source})[/bold white]",
                border_style="green",
                box=box.ROUNDED,
            )
        )
    else:
        # Check for media descriptions (Video visual description or VisionAnalyzer)
        video_data = results.get("VideoAnalyzer", {}).get("data", {})
        vision_data = results.get("VisionAnalyzer", {}).get("data", {})

        vis_desc = video_data.get("visual_description") or vision_data.get(
            "description"
        )
        vis_source = (
            "VideoAnalyzer"
            if video_data.get("visual_description")
            else ("VisionAnalyzer" if vision_data.get("description") else None)
        )

        if vis_desc:
            score_str = ""
            if "adult_content_score" in vision_data:
                score = vision_data["adult_content_score"]
                sfw_str = (
                    "[bold green]SFW[/bold green]"
                    if vision_data.get("is_sfw", True)
                    else "[bold red]NSFW[/bold red]"
                )
                score_str = f" | Safety: {sfw_str} (Score: {score}/10)"

            console.print(
                Panel(
                    Text(vis_desc, style="white"),
                    title=f"[bold white]👁️ Visual Content Description ({vis_source}{score_str})[/bold white]",
                    border_style="yellow",
                    box=box.ROUNDED,
                )
            )

    # 5. Security Alerts: Credentials & Passwords
    pwd_task = results.get("PasswordExtractor", {}).get("data", {})
    passwords = pwd_task.get("passwords", []) if isinstance(pwd_task, dict) else []

    if passwords:
        pwd_text = Text("\n".join([f"🔒 {p}" for p in passwords]), style="bold red")
        console.print(
            Panel(
                pwd_text,
                title="[bold yellow]⚠️ EXPOSED CREDENTIALS / PASSWORDS DETECTED[/bold yellow]",
                border_style="bold red",
                box=box.DOUBLE,
            )
        )

    # 6. Harvested PII (Personal Information)
    pii_task = results.get("PIIHarvester", {}).get("data", {})
    pii_entities = pii_task.get("pii", {}) if isinstance(pii_task, dict) else {}

    if pii_entities and any(pii_entities.values()):
        pii_table = Table(box=box.SIMPLE, border_style="dim yellow")
        pii_table.add_column("Type", style="bold yellow", width=22)
        pii_table.add_column("Extracted Entities", style="white")

        for key, label in [
            ("names", "Names"),
            ("emails", "Emails"),
            ("addresses", "Addresses"),
        ]:
            vals = pii_entities.get(key, [])
            if vals:
                formatted_vals = [format_pii_value(v) for v in vals]
                pii_table.add_row(label, ", ".join(formatted_vals))

        console.print(
            Panel(
                pii_table,
                title="[bold white]👤 Harvested Personally Identifiable Information (PII)[/bold white]",
                border_style="yellow",
                box=box.ROUNDED,
            )
        )

    # 7. Estate & Financial Relevance Check
    estate_data = results.get("EstateAnalyzer", {}).get("data", {})
    if estate_data and not estate_data.get("skipped", False):
        is_estate = estate_data.get("is_estate_document", False)
        reasoning = estate_data.get("reasoning", "")

        estate_text = Text.assemble(
            ("Estate Critical: ", "bold"),
            (
                "[bold green]YES[/bold green]"
                if is_estate
                else "[bold red]NO[/bold red]"
            ),
            ("\nReasoning: ", "bold dim"),
            (reasoning, "italic white"),
        )
        console.print(
            Panel(
                estate_text,
                title="[bold white]⚖️ Estate Plan & Legal/Financial Relevance[/bold white]",
                border_style="magenta",
                box=box.ROUNDED,
            )
        )

    # 8. OCR Quality Assessment
    ocr_data = results.get("OCRConfidenceScorer", {}).get("data", {})
    if ocr_data and not ocr_data.get("skipped", False):
        mean_conf = ocr_data.get("mean_confidence", 0.0)
        median_conf = ocr_data.get("median_confidence", 0.0)
        needs_review = ocr_data.get("needs_review", False)
        low_words = ocr_data.get("low_confidence_words", 0)
        total_words = ocr_data.get("total_words", 0)

        ocr_table = Table(box=box.SIMPLE, show_header=False, border_style="dim blue")
        ocr_table.add_column("Metric", style="bold blue", width=25)
        ocr_table.add_column("Value", style="white")

        ocr_table.add_row("Mean Word-Level Confidence", f"{mean_conf}%")
        ocr_table.add_row("Median Word-Level Confidence", f"{median_conf}%")
        ocr_table.add_row("Low Confidence Words (<60)", f"{low_words} / {total_words}")
        ocr_table.add_row(
            "Needs Manual Review Flag",
            (
                "[bold red]YES[/bold red]"
                if needs_review
                else "[bold green]NO[/bold green]"
            ),
        )

        console.print(
            Panel(
                ocr_table,
                title="[bold white]📸 OCR Quality Assessment[/bold white]",
                border_style="cyan",
                box=box.ROUNDED,
            )
        )

    # 9. Email Listings (EML/MBOX)
    email_data = results.get("EmailParser", {}).get("data", {})
    if email_data and email_data.get("emails"):
        emails_list = email_data.get("emails", [])
        total_emails = email_data.get("total_emails", len(emails_list))

        email_table = Table(box=box.SIMPLE, border_style="dim cyan")
        email_table.add_column("From", style="bold cyan", width=25)
        email_table.add_column("Subject", style="white", width=40)
        email_table.add_column("Attachments", style="yellow")

        for eml in emails_list[:5]:  # Display first 5
            from_addr = eml.get("from", "Unknown")
            subject = eml.get("subject", "No Subject")
            attachments = eml.get("attachments", [])
            att_names = (
                ", ".join([a.get("filename", "unnamed") for a in attachments]) or "None"
            )
            email_table.add_row(from_addr, subject, att_names)

        console.print(
            Panel(
                email_table,
                title=f"[bold white]✉️ Parsed Emails (Showing first 5 of {total_emails})[/bold white]",
                border_style="cyan",
                box=box.ROUNDED,
            )
        )

    # 10. Task Execution Log Summary
    task_table = Table(box=box.ROUNDED, border_style="dim white")
    task_table.add_column(
        "Analysis Task / Plugin", style="bold white", header_style="bold cyan"
    )
    task_table.add_column("Ver", style="dim", header_style="bold cyan")
    task_table.add_column("Status", header_style="bold cyan")
    task_table.add_column("Context / Details / Failures", header_style="bold cyan")

    for t_name, t_info in results.items():
        status = t_info.get("status", "PENDING")
        status_style = "bold yellow"
        if status == "COMPLETED":
            status_style = "bold green"
        elif status == "FAILED":
            status_style = "bold red"

        err = t_info.get("error") or ""
        details = f"[red]{err}[/red]" if err else ""

        if not err and t_info.get("data", {}).get("skipped"):
            details = (
                f"Skipped: {t_info.get('data', {}).get('reason', 'Conditions not met')}"
            )
        elif (
            not err
            and t_name == "LanguageDetector"
            and t_info.get("data", {}).get("language")
        ):
            details = f"Language: {t_info.get('data', {}).get('language_name')}"
        elif not err and t_name == "Router" and t_info.get("data", {}).get("category"):
            details = f"Category: {t_info.get('data', {}).get('category')}"
        elif (
            not err
            and t_name == "OCRConfidenceScorer"
            and t_info.get("data", {}).get("mean_confidence") is not None
        ):
            details = f"Mean Conf: {t_info.get('data', {}).get('mean_confidence')}%"

        task_table.add_row(
            t_name,
            str(t_info.get("version", "1.0")),
            f"[{status_style}]{status}[/{status_style}]",
            details,
        )

    console.print(
        Panel(
            task_table,
            title="[bold white]🛠️ Pipeline Tasks Execution Log[/bold white]",
            border_style="white",
            box=box.ROUNDED,
        )
    )
    console.print()


async def get_matching_files(path: str) -> list[Dict[str, Any]]:
    """Fetch all matching database info for a file path or filename pattern."""
    async with async_session_maker() as session:
        # 1. Try exact match first
        abs_path = str(Path(path).resolve())
        stmt = select(Document).where(Document.path == abs_path)
        result = await session.execute(stmt)
        docs = result.scalars().all()

        # 2. Try suffix/path fragment match if not found (e.g. 'rfb/Appointments.txt')
        if not docs:
            stmt = select(Document).where(Document.path.like(f"%{path}"))
            result = await session.execute(stmt)
            docs = result.scalars().all()

        # 3. Try filename basename match (e.g. 'Appointments.txt')
        if not docs:
            basename = os.path.basename(path)
            stmt = select(Document).where(Document.path.like(f"%{basename}"))
            result = await session.execute(stmt)
            docs = result.scalars().all()

        if not docs:
            return []

        all_infos = []
        for doc in docs:
            # Get Tasks
            task_stmt = select(AnalysisTask).where(AnalysisTask.document_id == doc.id)
            task_result = await session.execute(task_stmt)
            tasks = task_result.scalars().all()

            info = {
                "document": {
                    "id": doc.id,
                    "path": doc.path,
                    "mime_type": doc.mime_type,
                    "file_hash": doc.file_hash,
                    "file_size": doc.file_size,
                    "status": doc.status,
                    "created_at": doc.created_at.isoformat()
                    if doc.created_at
                    else None,
                    "mtime": doc.mtime,
                },
                "analysis_results": {},
            }

            for task in tasks:
                try:
                    data = json.loads(task.result_data) if task.result_data else {}
                except json.JSONDecodeError:
                    data = task.result_data

                info["analysis_results"][task.task_name] = {
                    "status": task.status,
                    "version": task.plugin_version,
                    "data": data,
                    "error": task.error_message,
                }
            all_infos.append(info)

        return all_infos


async def get_file_info(path: str) -> Optional[Dict[str, Any]]:
    """Fetch database info for a specific file path (retained for backward compatibility)."""
    matches = await get_matching_files(path)
    return matches[0] if matches else None


async def main():
    parser = argparse.ArgumentParser(
        description="Inspect all recorded metadata and analysis for a specific file or filename."
    )
    parser.add_argument(
        "path", type=str, help="Path or filename of the file to inspect."
    )
    parser.add_argument(
        "--no-image",
        action="store_true",
        help="Do not attempt to display terminal images.",
    )
    parser.add_argument(
        "--yaml",
        action="store_true",
        help="Output raw analysis results as YAML instead of the formatted Rich layout.",
    )
    args = parser.parse_args()

    # Initialize database
    await init_db()

    matches = await get_matching_files(args.path)

    if not matches:
        console.print(
            f"[bold red]Error:[/bold red] File not found in catalog database matching: {args.path}"
        )
        sys.exit(1)

    # 1. Output YAML or Rich
    if args.yaml:
        if len(matches) == 1:
            print(yaml.dump(matches[0], sort_keys=False, allow_unicode=True, indent=2))
        else:
            print(yaml.dump(matches, sort_keys=False, allow_unicode=True, indent=2))
    else:
        if len(matches) > 1:
            console.print(
                f"[bold yellow]🔍 Found {len(matches)} files matching filename/pattern '{args.path}':[/bold yellow]\n"
            )

        for idx, info in enumerate(matches):
            if len(matches) > 1:
                console.print(
                    f"[bold cyan]--- Match #{idx + 1} of {len(matches)} ---[/bold cyan]"
                )

            print_rich_analysis(info)

            # Display Image/Thumbnail if supported
            if not args.no_image:
                mime = info["document"]["mime_type"]
                path = info["document"]["path"]

                if mime:
                    term = os.environ.get("TERM_PROGRAM", "")
                    is_iterm = term == "iTerm.app"

                    if is_iterm:
                        if mime.startswith("image/"):
                            console.print(
                                "\n[bold cyan]--- iTerm2 Inline Visual Preview ---[/bold cyan]"
                            )
                            display_image_iterm2(path)
                        elif mime.startswith("video/"):
                            console.print(
                                "\n[bold cyan]--- Video Keyframe Preview (5% Start Offset) ---[/bold cyan]"
                            )
                            try:
                                plugin = VideoAnalyzerPlugin()
                                temp_thumb = plugin.extract_keyframes(path, count=1)
                                if temp_thumb:
                                    display_image_iterm2(temp_thumb[0])
                                    # Cleanup
                                    if os.path.exists(temp_thumb[0]):
                                        os.remove(temp_thumb[0])
                            except Exception as e:
                                console.print(
                                    f"[dim](Could not extract video keyframe preview: {e})[/dim]"
                                )

            if len(matches) > 1 and idx < len(matches) - 1:
                console.print("\n" + "═" * console.width + "\n")


if __name__ == "__main__":
    asyncio.run(main())
