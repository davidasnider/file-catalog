import argparse
import hashlib
import os
from pathlib import Path
from collections import defaultdict
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def compute_md5(file_path: str, chunk_size: int = 8192) -> str:
    """Compute MD5 hash of a file efficiently by reading it in chunks."""
    hasher = hashlib.md5()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def find_duplicates(directory: str):
    """Recursively find and group files by their MD5 hashes."""
    hashes = defaultdict(list)
    base_path = Path(directory).resolve()

    if not base_path.exists() or not base_path.is_dir():
        logger.error(f"Error: {directory} is not a valid directory.")
        return hashes

    logger.info(f"🔍 Scanning {base_path} for duplicates...")

    for root, _, files in os.walk(base_path):
        for filename in files:
            file_path = os.path.join(root, filename)
            # Skip symlinks to avoid accidental deletion of original targets
            if os.path.islink(file_path):
                continue

            try:
                file_hash = compute_md5(file_path)
                hashes[file_hash].append(file_path)
            except (PermissionError, OSError) as e:
                logger.error(f"⚠️  Could not read {file_path}: {e}")

    return hashes


def delete_duplicates(hashes: dict, dry_run: bool = False):
    """Keep the shortest path version of each file and delete the rest."""
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
                except Exception as e:
                    logger.error(f"  ❌ Error processing {dup_path}: {e}")

    if total_deleted > 0:
        status = "[DRY RUN] Would have deleted" if dry_run else "Successfully deleted"
        logger.info(f"\n✨ {status} {total_deleted} duplicate files.")
        logger.info(
            f"📦 Total space {'to be saved' if dry_run else 'saved'}: {total_saved_space} bytes."
        )
    else:
        logger.info("\n✅ No duplicates found.")


def main():
    parser = argparse.ArgumentParser(
        description="Find and delete duplicate files based on MD5 hashes, keeping the one with the shortest path."
    )
    parser.add_argument(
        "directory", type=str, help="Path to the directory to scan for duplicates."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting anything.",
    )

    args = parser.parse_args()

    hashes = find_duplicates(args.directory)
    delete_duplicates(hashes, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
