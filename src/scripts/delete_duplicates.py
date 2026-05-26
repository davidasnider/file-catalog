import argparse
import hashlib
import os
import stat
from pathlib import Path
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    """Configure logging for this module.

    Called once from main() so that importing helpers does not
    mutate global logging state.
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")


def compute_sha256(file_path: str, chunk_size: int = 8192) -> str:
    """Compute SHA-256 hash of a file efficiently by reading it in chunks."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def find_duplicates(directory: str) -> dict[str, list[str]] | None:
    """Recursively find and group files by their SHA-256 hashes.

    Uses a two-phase approach for efficiency:
    1. Group candidates by file size (exact size match required).
    2. Only compute full SHA-256 hashes for size-colliding groups.

    Args:
        directory: Path to the directory to scan.

    Returns:
        A dictionary mapping SHA-256 hashes to lists of file paths,
        or None if the directory is invalid.
    """
    hashes: defaultdict[str, list[str]] = defaultdict(list)
    base_path = Path(directory).resolve()

    if not base_path.exists() or not base_path.is_dir():
        logger.error(f"Error: {directory} is not a valid directory.")
        return None

    logger.info(f"🔍 Scanning {base_path} for duplicates...")

    # Phase 1: Group by file size (fast, no hashing)
    size_groups: defaultdict[int, list[str]] = defaultdict(list)
    seen_inodes: dict[tuple[int, int], str] = {}  # (dev, ino) -> path

    for root, _, files in os.walk(base_path):
        for filename in files:
            file_path = os.path.join(root, filename)

            # Skip symlinks to avoid accidental deletion of original targets
            if os.path.islink(file_path):
                continue

            try:
                stat_result = os.stat(file_path)
            except (PermissionError, OSError) as e:
                logger.error(f"⚠️  Could not stat {file_path}: {e}")
                continue

            # Skip non-regular files (FIFOs, device nodes, etc.)
            if not stat.S_ISREG(stat_result.st_mode):
                continue

            # Skip hardlinks beyond the first occurrence (same inode on same device)
            inode_key = (stat_result.st_dev, stat_result.st_ino)
            if inode_key in seen_inodes:
                continue
            seen_inodes[inode_key] = file_path

            size_groups[stat_result.st_size].append(file_path)

    # Phase 2: Only hash files that share a size with at least one other
    for size, paths in size_groups.items():
        if len(paths) < 2:
            # Unique size — cannot be a duplicate
            continue

        for file_path in paths:
            try:
                file_hash = compute_sha256(file_path)
                hashes[file_hash].append(file_path)
            except (PermissionError, OSError) as e:
                logger.error(f"⚠️  Could not read {file_path}: {e}")

    # Filter to only include hashes with 2+ paths (actual duplicates)
    duplicates = {h: paths for h, paths in hashes.items() if len(paths) > 1}
    return duplicates


def delete_duplicates(hashes: dict[str, list[str]], dry_run: bool = False) -> None:
    """Keep the shortest path version of each file and delete the rest.

    Args:
        hashes: Dictionary mapping SHA-256 hashes to lists of file paths,
                where each list contains 2+ paths (actual duplicates).
        dry_run: If True, only report what would be deleted.
    """
    total_deleted = 0
    total_saved_space = 0
    duplicates_found = 0

    for file_hash, paths in hashes.items():
        # Sort paths by length (shortest first), then alphabetically for stability
        sorted_paths = sorted(paths, key=lambda p: (len(p), p))

        keep_path = sorted_paths[0]
        dup_paths = sorted_paths[1:]
        duplicates_found += len(dup_paths)

        logger.info(f"\n💎 Found {len(paths)} versions of hash {file_hash[:8]}...")
        logger.info(f"  ✅ Keeping: {keep_path}")

        for dup_path in dup_paths:
            try:
                file_size = os.path.getsize(dup_path)
                if dry_run:
                    logger.info(
                        f"  [DRY RUN] Would delete: {dup_path} ({file_size} bytes)"
                    )
                else:
                    os.remove(dup_path)
                    logger.info(f"  🗑️  Deleted: {dup_path}")

                total_deleted += 1
                total_saved_space += file_size
            except (OSError, PermissionError, FileNotFoundError) as e:
                logger.error(f"  ❌ Error processing {dup_path}: {e}")

    if duplicates_found == 0:
        logger.info("\n✅ No duplicates found.")
    elif total_deleted > 0:
        status = " [DRY RUN] Would have deleted" if dry_run else "Successfully deleted"
        logger.info(f"\n✨{status} {total_deleted} duplicate files.")
        logger.info(
            f"📦 Total space {'to be saved' if dry_run else 'saved'}: {total_saved_space} bytes."
        )
    else:
        logger.info(
            f"\n⚠️  Found {duplicates_found} duplicate file(s) but could not delete any "
            "(check permissions)."
        )


def main():
    _setup_logging()

    parser = argparse.ArgumentParser(
        description="Find and delete duplicate files based on SHA-256 hashes, keeping the one with the shortest path."
    )
    parser.add_argument(
        "directory", type=str, help="Path to the directory to scan for duplicates."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting anything.",
    )
    parser.add_argument(
        "--allow-cwd",
        action="store_true",
        help="Allow scanning the current working directory (use with caution).",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation prompt before deleting files.",
    )

    args = parser.parse_args()

    if Path(args.directory).resolve() == Path.cwd().resolve() and not args.allow_cwd:
        parser.error(
            "Scanning the current directory without --allow-cwd is not allowed "
            "to prevent accidental self-deletion. Use --allow-cwd to override."
        )

    hashes = find_duplicates(args.directory)
    if hashes is None:
        raise SystemExit(2)

    if not args.dry_run and not args.yes and hashes:
        dup_count = sum(len(paths) - 1 for paths in hashes.values())
        confirm = input(
            f"This will delete {dup_count} duplicate file(s). Are you sure? (y/N): "
        )
        if confirm.strip().lower() != "y":
            logger.info("Operation cancelled.")
            raise SystemExit(1)

    delete_duplicates(hashes, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
