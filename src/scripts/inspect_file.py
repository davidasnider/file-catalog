import argparse
import asyncio
import json
import os
import sys
import base64
from pathlib import Path
from typing import Dict, Any, Optional

import yaml
from sqlalchemy import select

from src.db.engine import async_session_maker
from src.db.models import Document, AnalysisTask
from src.plugins.video_analyzer import VideoAnalyzerPlugin


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


async def get_file_info(path: str) -> Optional[Dict[str, Any]]:
    """Fetch all database info for a specific file path."""
    abs_path = str(Path(path).resolve())

    async with async_session_maker() as session:
        # Get Document
        stmt = select(Document).where(Document.path == abs_path)
        result = await session.execute(stmt)
        doc = result.scalar_one_or_none()

        if not doc:
            return None

        # Get Tasks
        task_stmt = select(AnalysisTask).where(AnalysisTask.document_id == doc.id)
        task_result = await session.execute(task_stmt)
        tasks = task_result.scalars().all()

        info = {
            "document": {
                "id": doc.id,
                "path": doc.path,
                "mime_type": doc.mime_type,
                "file_size": doc.file_size,
                "status": doc.status,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
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

        return info


async def main():
    parser = argparse.ArgumentParser(
        description="Inspect all recorded metadata and analysis for a specific file."
    )
    parser.add_argument("path", type=str, help="Path to the file to inspect.")
    parser.add_argument(
        "--no-image",
        action="store_true",
        help="Do not attempt to display terminal images.",
    )
    args = parser.parse_args()

    info = await get_file_info(args.path)

    if not info:
        print(f"Error: File not found in database: {args.path}")
        sys.exit(1)

    # 1. Output YAML
    print(yaml.dump(info, sort_keys=False, allow_unicode=True, indent=2))

    # 2. Display Image/Thumbnail if supported
    if not args.no_image:
        mime = info["document"]["mime_type"]
        path = info["document"]["path"]

        term = os.environ.get("TERM_PROGRAM", "")
        is_iterm = term == "iTerm.app"

        if is_iterm:
            if mime.startswith("image/"):
                print("\n--- Visual Preview ---")
                display_image_iterm2(path)
            elif mime.startswith("video/"):
                print("\n--- Video Thumbnail (Middle Frame) ---")
                try:
                    plugin = VideoAnalyzerPlugin()
                    temp_thumb = plugin.extract_keyframes(path, count=1)
                    if temp_thumb:
                        display_image_iterm2(temp_thumb[0])
                        # Cleanup
                        if os.path.exists(temp_thumb[0]):
                            os.remove(temp_thumb[0])
                except Exception as e:
                    print(f"(Could not extract video thumbnail: {e})")


if __name__ == "__main__":
    asyncio.run(main())
