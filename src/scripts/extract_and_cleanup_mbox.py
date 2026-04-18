"""
Bulk extract mailbox files (.mbox, .mbx, etc.) into individual .eml files,
grouping conversation threads into subdirectories.

This mirrors the archive extraction pattern in extract_and_cleanup_archives.py.
After extraction, the original mailbox file can optionally be deleted so the
scanner picks up individual emails on the next pass.

Usage:
    python -m src.scripts.extract_and_cleanup_mbox /path/to/archive --dry-run
    python -m src.scripts.extract_and_cleanup_mbox /path/to/archive
    python -m src.scripts.extract_and_cleanup_mbox /path/to/archive --keep
"""

import argparse
import email
import email.generator
import email.policy
import io
import logging
import os
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.core.mbox_utils import RobustMbox

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Extensions that are treated as mailbox files.
MAILBOX_EXTENSIONS = {".mbox", ".mbx", ".mbs"}

# Maximum filename length (most filesystems cap at 255 bytes).
MAX_FILENAME_LEN = 120

# Pattern to strip reply/forward prefixes from subjects for thread grouping.
_REPLY_PREFIX_RE = re.compile(
    r"^(re|fwd?|aw|sv|vs|ref|rif)\s*(\[\d+\])?\s*:\s*",
    re.IGNORECASE,
)


def _normalize_subject(subject: str) -> str:
    """Strip reply/forward prefixes and normalize whitespace for thread grouping."""
    if not subject:
        return ""
    cleaned = subject.strip()
    # Iteratively strip prefixes (handles "Re: Re: Fwd: ...")
    prev = None
    while prev != cleaned:
        prev = cleaned
        cleaned = _REPLY_PREFIX_RE.sub("", cleaned).strip()
    return cleaned


def _sanitize_filename(name: str, max_len: int = MAX_FILENAME_LEN) -> str:
    """
    Produce a filesystem-safe filename from an arbitrary string.

    - Normalizes unicode
    - Replaces unsafe characters with underscores
    - Collapses runs of underscores
    - Truncates to max_len
    """
    if not name:
        return "unnamed"

    # Normalize unicode
    name = unicodedata.normalize("NFKD", name)

    # Replace anything that isn't alphanumeric, hyphen, period, or space
    name = re.sub(r"[^\w\s\-.]", "_", name)
    # Collapse whitespace and underscores
    name = re.sub(r"[\s_]+", "_", name).strip("_. ")

    if not name:
        return "unnamed"

    return name[:max_len]


def _extract_addr_local(from_header: str) -> str:
    """Extract just the local part of an email address for filenames."""
    if not from_header:
        return "unknown"
    # Try to find an email address in angle brackets
    match = re.search(r"<([^>]+)>", from_header)
    addr = match.group(1) if match else from_header.strip()
    # Take local part before @
    local = addr.split("@")[0] if "@" in addr else addr
    return _sanitize_filename(local, max_len=30)


def _extract_date_prefix(date_header: str) -> str:
    """Extract a sortable date prefix from an email Date header."""
    if not date_header:
        return "0000-00-00"
    try:
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(date_header)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return "0000-00-00"


def _extract_sort_timestamp(date_header: str) -> float:
    """Extract a sortable timestamp from an email Date header."""
    if not date_header:
        return 0.0
    try:
        from email.utils import parsedate_to_datetime
        from datetime import timezone

        dt = parsedate_to_datetime(date_header)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0.0


def _get_message_id(msg: email.message.Message) -> Optional[str]:
    """Extract the Message-ID header, stripping angle brackets."""
    mid = msg.get("Message-ID", "")
    if mid:
        return mid.strip().strip("<>")
    return None


def _get_references(msg: email.message.Message) -> List[str]:
    """Extract all referenced message IDs from In-Reply-To and References headers."""
    refs = []

    in_reply_to = msg.get("In-Reply-To", "")
    if in_reply_to:
        # Can contain multiple IDs separated by whitespace
        for ref in re.findall(r"<([^>]+)>", in_reply_to):
            refs.append(ref)

    references = msg.get("References", "")
    if references:
        for ref in re.findall(r"<([^>]+)>", references):
            if ref not in refs:
                refs.append(ref)

    return refs


def _is_mailbox_file(file_path: Path) -> bool:
    """Determine if a file is a mailbox by extension or MIME type detection.

    Args:
        file_path: Path to the file to check.

    Returns:
        bool: True if the file is likely a mailbox.
    """
    suffix = file_path.suffix.lower()

    # Explicitly skip .txt files — they are never mailboxes for our purposes.
    if suffix == ".txt":
        return False

    # Match on known extensions, including numbered variants like .mbx.002
    if suffix in MAILBOX_EXTENSIONS:
        return True

    # Check all suffixes for cases like "In.mbx.002"
    for s in file_path.suffixes:
        if s.lower() in MAILBOX_EXTENSIONS:
            return True

    # Try MIME type detection as a fallback
    try:
        import magic

        mime = magic.from_file(str(file_path), mime=True)
        if mime == "application/mbox":
            return True
    except Exception:
        pass

    return False


def _build_threads(
    messages: List[email.message.Message],
) -> Tuple[Dict[str, List[email.message.Message]], List[email.message.Message]]:
    """
    Group messages into conversation threads.

    Strategy:
    1. Build a graph using Message-ID, In-Reply-To, and References headers.
    2. Fall back to normalized subject line for messages without threading headers.
    3. Messages that belong to no thread (unique subject, no references) are standalone.

    Returns:
        (threads_dict, standalone_list)
        threads_dict: {thread_key: [messages sorted by date]}
        standalone_list: [messages with no thread]
    """
    # Phase 1: Build message-ID based thread graph
    # Maps message-id -> thread_id (the root message-id of the thread)
    id_to_thread: Dict[str, str] = {}

    # Union-find style: link each message to its references
    def find_root(mid: str) -> str:
        visited = set()
        current = mid
        while current in id_to_thread and id_to_thread[current] != current:
            if current in visited:
                break
            visited.add(current)
            current = id_to_thread[current]
        # Path compression
        compress = mid
        while compress in id_to_thread and id_to_thread[compress] != current:
            next_id = id_to_thread[compress]
            id_to_thread[compress] = current
            compress = next_id
        return current

    for msg in messages:
        mid = _get_message_id(msg)
        refs = _get_references(msg)

        if mid and mid not in id_to_thread:
            id_to_thread[mid] = mid

        if mid and refs:
            # Link this message to the first reference (root of the thread)
            root = find_root(refs[0]) if refs[0] in id_to_thread else refs[0]
            for ref in refs:
                if ref not in id_to_thread:
                    id_to_thread[ref] = root
                else:
                    # Merge trees
                    ref_root = find_root(ref)
                    if ref_root != root:
                        id_to_thread[ref_root] = root
            if mid:
                id_to_thread[mid] = root

    # Phase 2: Group by thread root, fall back to subject
    thread_groups: Dict[str, List[email.message.Message]] = defaultdict(list)
    subject_groups: Dict[str, List[email.message.Message]] = defaultdict(list)
    standalone = []

    for msg in messages:
        mid = _get_message_id(msg)
        refs = _get_references(msg)

        if mid and mid in id_to_thread:
            root = find_root(mid)
            thread_groups[root].append(msg)
        elif refs:
            # Message has references but no message-id of its own
            root = find_root(refs[0]) if refs[0] in id_to_thread else refs[0]
            thread_groups[root].append(msg)
        else:
            # No threading headers — fall back to subject
            subj = _normalize_subject(str(msg.get("Subject", "")))
            if subj:
                subject_groups[subj].append(msg)
            else:
                standalone.append(msg)

    # Phase 3: Merge subject groups into threads or standalone
    threads: Dict[str, List[email.message.Message]] = {}
    thread_counter = 0

    # ID-based threads
    for root_id, msgs in thread_groups.items():
        if len(msgs) >= 2:
            thread_counter += 1
            # Sort by date
            msgs.sort(key=lambda m: _extract_sort_timestamp(str(m.get("Date", ""))))
            # Use the normalized subject of the first message as the thread name
            subj = _normalize_subject(str(msgs[0].get("Subject", ""))) or "no_subject"
            thread_key = (
                f"thread_{thread_counter:03d}_{_sanitize_filename(subj, max_len=60)}"
            )
            threads[thread_key] = msgs
        else:
            # Single message "thread" — treat as standalone
            standalone.extend(msgs)

    # Subject-based groups
    for subj, msgs in subject_groups.items():
        if len(msgs) >= 2:
            thread_counter += 1
            msgs.sort(key=lambda m: _extract_sort_timestamp(str(m.get("Date", ""))))
            thread_key = (
                f"thread_{thread_counter:03d}_{_sanitize_filename(subj, max_len=60)}"
            )
            threads[thread_key] = msgs
        else:
            standalone.extend(msgs)

    return threads, standalone


def _write_eml(msg: email.message.Message, dest_path: Path):
    """Write an email.message.Message to a .eml file.

    Args:
        msg: The message to write.
        dest_path: The destination path for the .eml file.
    """
    try:
        with open(dest_path, "wb") as f:
            # Try standard BytesGenerator first (fastest, preserves binary if possible)
            gen = email.generator.BytesGenerator(f, policy=email.policy.default)
            gen.flatten(msg)
    except UnicodeEncodeError:
        # Fallback for messages containing characters (like \ufffd) that BytesGenerator
        # can't handle with its default 'ascii' + 'surrogateescape' strategy.
        # We use a string-based Generator and encode the entire result to UTF-8.
        with io.StringIO() as s_io:
            gen = email.generator.Generator(s_io, policy=email.policy.default)
            gen.flatten(msg)
            with open(dest_path, "wb") as f:
                f.write(s_io.getvalue().encode("utf-8", errors="replace"))


def _make_eml_filename(msg: email.message.Message, index: int) -> str:
    """Generate a descriptive .eml filename from message headers."""
    # Ensure headers are converted to string safely
    date_header = msg.get("Date", "")
    date_prefix = _extract_date_prefix(str(date_header))

    from_header = msg.get("From", "")
    from_part = _extract_addr_local(str(from_header))

    subject_header = msg.get("Subject", "")
    subject = _sanitize_filename(str(subject_header), max_len=50) or "no_subject"

    # Include index to guarantee uniqueness
    return f"{date_prefix}_{index:04d}_{from_part}_{subject}.eml"


def extract_mailbox(file_path: Path, dest_dir: Path) -> int:
    """Extract a mailbox file into individual .eml files with thread grouping.

    Args:
        file_path: Path to the mailbox file.
        dest_dir: Path to the directory where .eml files will be saved.

    Returns:
        int: Total number of emails extracted.
    """
    logger.info(f"Parsing mailbox: {file_path}")

    # Use RobustMbox to handle legacy encodings in From lines
    mbox = RobustMbox(str(file_path))
    messages = []
    try:
        for msg in mbox:
            messages.append(msg)
    finally:
        mbox.close()

    if not messages:
        logger.warning(f"No messages found in {file_path}")
        return 0

    logger.info(f"Found {len(messages)} messages in {file_path}")

    # Build threads
    threads, standalone = _build_threads(messages)

    logger.info(
        f"Grouped into {len(threads)} threads and {len(standalone)} standalone emails"
    )

    os.makedirs(dest_dir, exist_ok=True)
    email_count = 0

    # Write threaded emails
    for thread_key, msgs in threads.items():
        thread_dir = dest_dir / thread_key
        os.makedirs(thread_dir, exist_ok=True)
        for i, msg in enumerate(msgs):
            filename = _make_eml_filename(msg, i + 1)
            _write_eml(msg, thread_dir / filename)
            email_count += 1

    # Write standalone emails
    for i, msg in enumerate(standalone):
        filename = _make_eml_filename(msg, i + 1)
        _write_eml(msg, dest_dir / filename)
        email_count += 1

    return email_count


def process_directory(
    directory: str, recursive: bool = True, dry_run: bool = False, keep: bool = False
):
    """Walk a directory and extract all mailbox files found."""
    base_path = Path(directory)
    if not base_path.exists():
        logger.error(f"Directory {directory} does not exist.")
        return

    all_files = []
    if recursive:
        for root, _, files in os.walk(base_path):
            for f in files:
                all_files.append(Path(root) / f)
    else:
        all_files = [f for f in base_path.iterdir() if f.is_file()]

    mailboxes_processed = 0

    for file_path in all_files:
        if not _is_mailbox_file(file_path):
            continue

        # Strip mailbox suffixes without removing legitimate numeric filename parts:
        # "In.mbx.002" -> "In_extracted"
        # "project.2024.mbox" -> "project.2024_extracted"
        mailbox_suffixes = {".mbox", ".mbx", ".mbs"}
        suffixes = [suffix.lower() for suffix in file_path.suffixes]
        suffixes_to_strip = 0

        if suffixes:
            if suffixes[-1] in mailbox_suffixes:
                suffixes_to_strip = 1
            elif (
                len(suffixes) >= 2
                and suffixes[-1][1:].isdigit()
                and suffixes[-2] in mailbox_suffixes
            ):
                suffixes_to_strip = 2

        base_name = file_path.name
        for _ in range(suffixes_to_strip):
            base_name = Path(base_name).stem

        if not base_name:
            base_name = file_path.stem

        dest_folder = file_path.parent / f"{base_name}_extracted"

        # Avoid collisions
        counter = 1
        original_dest = dest_folder
        while dest_folder.exists():
            dest_folder = Path(f"{original_dest}_{counter}")
            counter += 1

        if dry_run:
            logger.info(f"[DRY RUN] Would extract {file_path} to {dest_folder}")
            if not keep:
                logger.info(f"[DRY RUN] Would remove original mailbox {file_path}")
            mailboxes_processed += 1
            continue

        logger.info(f"Extracting {file_path} to {dest_folder}...")

        try:
            email_count = extract_mailbox(file_path, dest_folder)
            if email_count > 0:
                logger.info(
                    f"Successfully extracted {email_count} emails from {file_path}"
                )
                if keep:
                    logger.info(f"Keeping original: {file_path}")
                else:
                    logger.info(f"Removing original mailbox: {file_path}")
                    try:
                        os.remove(file_path)
                    except Exception as e:
                        logger.error(f"Failed to remove {file_path}: {e}")
                mailboxes_processed += 1
            else:
                logger.warning(
                    f"No emails extracted from {file_path}. Keeping original."
                )
        except Exception as e:
            logger.error(f"Extraction failed for {file_path}: {e}")
            logger.info("Keeping original mailbox.")

    operation = "simulated" if dry_run else "completed"
    action = "and removed" if not keep else "and kept"
    logger.info(
        f"Done. Processed {operation} {mailboxes_processed} mailboxes {action}."
    )


def main():
    parser = argparse.ArgumentParser(
        description="Bulk extract mailbox files into individual .eml files, "
        "grouping conversation threads into subdirectories."
    )
    parser.add_argument("directory", help="The directory to scan for mailbox files.")
    parser.add_argument(
        "--no-recursive",
        action="store_false",
        dest="recursive",
        help="Do not scan subdirectories.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without extracting or deleting anything.",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Extract mailboxes but do NOT delete the original source files.",
    )

    args = parser.parse_args()

    if args.dry_run:
        logger.info("--- DRY RUN MODE ---")
        process_directory(args.directory, args.recursive, dry_run=True, keep=args.keep)
        return

    msg = f"This will EXTRACT mailboxes in '{args.directory}'"
    if not args.keep:
        msg += " and DELETE the originals"
    msg += ". Are you sure? (y/N): "

    confirm = input(msg)
    if confirm.lower() == "y":
        process_directory(args.directory, args.recursive, dry_run=False, keep=args.keep)
    else:
        logger.info("Operation cancelled.")


if __name__ == "__main__":
    main()
