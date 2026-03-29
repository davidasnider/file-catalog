import os
import zipfile
import tarfile
import logging
import argparse
from pathlib import Path

try:
    import py7zr

    HAS_7Z = True
except ImportError:
    HAS_7Z = False

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def extract_archive(file_path: Path, dest_dir: Path):
    """Extracts a single archive based on its extension."""
    suffix = file_path.suffix.lower()

    try:
        if suffix == ".zip":
            with zipfile.ZipFile(file_path, "r") as zip_ref:
                zip_ref.extractall(dest_dir)
            return True
        elif suffix in (".tar", ".gz", ".bz2", ".xz", ".tgz"):
            with tarfile.open(file_path, "r:*") as tar_ref:
                tar_ref.extractall(dest_dir)
            return True
        elif suffix == ".7z":
            if HAS_7Z:
                with py7zr.SevenZipFile(file_path, mode="r") as archive:
                    archive.extractall(path=dest_dir)
                return True
            else:
                logger.warning(f"Skipping {file_path}: py7zr is not installed.")
                return False
        else:
            logger.debug(f"Unsupported archive format: {suffix}")
            return False
    except Exception as e:
        logger.error(f"Failed to extract {file_path}: {e}")
        return False


def process_directory(
    directory: str, recursive: bool = True, dry_run: bool = False, keep: bool = False
):
    base_path = Path(directory)
    if not base_path.exists():
        logger.error(f"Directory {directory} does not exist.")
        return

    # Supported extensions
    extensions = {".zip", ".tar", ".gz", ".bz2", ".xz", ".tgz", ".7z"}

    archives_processed = 0

    # We walk the directory. Note: extracting files might create more archives,
    # but we only process what we find in the initial pass to avoid infinite loops.
    all_files = []
    if recursive:
        for root, _, files in os.walk(base_path):
            for f in files:
                all_files.append(Path(root) / f)
    else:
        all_files = [f for f in base_path.iterdir() if f.is_file()]

    for file_path in all_files:
        if file_path.suffix.lower() in extensions:
            # Create a destination directory named after the archive (without extension)
            # but ensure it's in the same parent directory.
            dest_folder = file_path.parent / f"{file_path.stem}_extracted"

            # If folder exists, we might want to avoid overwriting or add a suffix
            counter = 1
            original_dest = dest_folder
            while dest_folder.exists():
                dest_folder = Path(f"{original_dest}_{counter}")
                counter += 1

            if dry_run:
                logger.info(f"[DRY RUN] Would extract {file_path} to {dest_folder}")
                if not keep:
                    logger.info(f"[DRY RUN] Would remove original archive {file_path}")
                archives_processed += 1
                continue

            logger.info(f"Extracting {file_path} to {dest_folder}...")

            if extract_archive(file_path, dest_folder):
                if keep:
                    logger.info(
                        f"Successfully extracted {file_path}. Keeping original."
                    )
                    archives_processed += 1
                else:
                    logger.info(
                        f"Successfully extracted. Removing source archive {file_path}..."
                    )
                    try:
                        os.remove(file_path)
                        archives_processed += 1
                    except Exception as e:
                        logger.error(f"Failed to remove {file_path}: {e}")
            else:
                logger.error(f"Extraction failed for {file_path}. Keeping original.")

    operation = "simulated" if dry_run else "completed"
    action = "and removed" if not keep else "and kept"
    logger.info(f"Done. Processed {operation} {archives_processed} archives {action}.")


def main():
    parser = argparse.ArgumentParser(
        description="Bulk extract archives and optionally remove originals."
    )
    parser.add_argument("directory", help="The directory to scan for archives.")
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
        help="Extract archives but do NOT delete the original source files.",
    )

    args = parser.parse_args()

    if args.dry_run:
        logger.info("--- DRY RUN MODE ---")
        process_directory(args.directory, args.recursive, dry_run=True, keep=args.keep)
        return

    msg = f"This will EXTRACT archives in '{args.directory}'"
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
