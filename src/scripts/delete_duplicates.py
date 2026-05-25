import argparse
import hashlib
import os
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
    """Compute SHA-256 hash of a file efficiently by reading it in chunks.

    Uses usedforsecurity=False to avoid failures on FIPS-restricted systems.
    """
    hasher = hashlib.sha256(usedforsecurity=False)
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
                stat = os.stat(file_path)
            except (PermissionError, OSError) as e:
                logger.error(f"⚠️  Could not stat {file_path}: {e}")
                continue

            # Skip hardlinks beyond the first occurrence (same inode on same device)
            inode_key = (stat.st_dev, stat.st_ino)
            if inode_key in seen_inodes:
                continue
            seen_inodes[inode_key] = file_path

            size_groups[stat.st_size].append(file_path)

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

    return hashes


def delete_duplicates(hashes: dict[str, list[str]], dry_run: bool = False) -> None:
    """Keep the shortest path version of each file and delete the rest.

    Args:
        hashes: Dictionary mapping SHA-256 hashes to lists of file paths.
        dry_run: If True, only report what would be deleted.
    """
    total_deleted = 0
    total_saved_space = 0

    for file_hash, paths in hashes.items():
        if len(paths) > 1:
            # Sort paths by length (shortest first), then alphabetically for stability
            sorted_paths = sorted(paths, key=lambda p: (len(p), p))

            keep_path = sorted_paths[0]
            duplicates = sorted_paths[1:]

            logger.info(f"\n💎 Found {len(paths)} versions of hash {file_hash[:8]}...")
            logger.info(f"  ✅ Keeping: {keep_path}")

            for dup_path in duplicates:
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

    if total_deleted > 0:
        status = " [DRY RUN] Would have deleted" if dry_run else "Successfully deleted"
        logger.info(f"\n✨{status} {total_deleted} duplicate files.")
        logger.info(
            f"📦 Total space {'to be saved' if dry_run else 'saved'}: {total_saved_space} bytes."
        )
    else:
        logger.info("\n✅ No duplicates found.")


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
        "--force",
        action="store_true",
        help="Allow scanning the current directory (use with caution).",
    )

    args = parser.parse_args()

    if Path(args.directory).resolve() == Path.cwd().resolve() and not args.force:
        parser.error(
            "Scanning the current directory without --force is not allowed "
            "to prevent accidental self-deletion. Use --force to override."
        )

    hashes = find_duplicates(args.directory)
    if hashes is None:
        raise SystemExit(2)

    delete_duplicates(hashes, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
