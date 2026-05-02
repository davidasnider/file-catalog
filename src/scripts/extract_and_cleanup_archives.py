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


def is_within_directory(directory: Path, target: Path):
    """Checks if a target path is within a directory (prevents path traversal)."""
    abs_directory = directory.resolve()
    abs_target = target.resolve()
    return abs_target.is_relative_to(abs_directory)


def safe_extract_zip(zip_ref: zipfile.ZipFile, dest_dir: Path):
    """Safely extracts a ZIP file, checking for path traversal and symlinks."""
    for member in zip_ref.infolist():
        # Check for path traversal in the filename itself
        target_path = (dest_dir / member.filename).resolve()
        if not is_within_directory(dest_dir, target_path):
            raise Exception(f"Potential path traversal attempt: {member.filename}")

        # ZIP files can contain symlinks. We extract member-by-member to ensure
        # that even if a symlink is created, we don't follow it for subsequent members.
        zip_ref.extract(member, dest_dir)


def safe_extract_7z(archive: "py7zr.SevenZipFile", dest_dir: Path):
    """Safely extracts a 7z file, checking for path traversal."""
    for member in archive.get_files():
        member_path = (dest_dir / member.filename).resolve()
        if not is_within_directory(dest_dir, member_path):
            raise Exception(f"Potential path traversal attempt: {member.filename}")

        # Check for symlinks if supported by the member object
        if hasattr(member, "is_symlink") and member.is_symlink():
            link_target = Path(member.link_target)
            if link_target.is_absolute():
                raise Exception(
                    f"Potential path traversal attempt (absolute link): {member.filename} -> {member.link_target}"
                )
            member_parent = (dest_dir / member.filename).parent
            resolved_link_target = (member_parent / link_target).resolve()
            if not is_within_directory(dest_dir, resolved_link_target):
                raise Exception(
                    f"Potential path traversal attempt (link target outside): {member.filename} -> {member.link_target}"
                )

    archive.extractall(path=dest_dir)


def safe_extract_tar(tar_ref: tarfile.TarFile, dest_dir: Path):
    """Safely extracts a Tar file, checking for path traversal or using filters."""
    # If Python 3.12+, use the 'data' filter for safety.
    if hasattr(tarfile, "data_filter"):
        tar_ref.extractall(dest_dir, filter="data")
    else:
        for member in tar_ref.getmembers():
            member_path = (dest_dir / member.name).resolve()
            if not is_within_directory(dest_dir, member_path):
                raise Exception(f"Potential path traversal attempt: {member.name}")

            # Check for symlinks and hardlinks traversal
            if member.issym() or member.islnk():
                link_target = Path(member.linkname)
                if link_target.is_absolute():
                    raise Exception(
                        f"Potential path traversal attempt (absolute link): {member.name} -> {member.linkname}"
                    )

                # Resolve the link target relative to the member's parent directory
                member_parent = (dest_dir / member.name).parent
                resolved_link_target = (member_parent / link_target).resolve()
                if not is_within_directory(dest_dir, resolved_link_target):
                    raise Exception(
                        f"Potential path traversal attempt (link target outside): {member.name} -> {member.linkname}"
                    )
        tar_ref.extractall(dest_dir)


def extract_archive(file_path: Path, dest_dir: Path):
    """Extracts a single archive based on its extension."""
    suffix = file_path.suffix.lower()
    # Check for multi-part extensions like .tar.gz
    suffixes = [s.lower() for s in file_path.suffixes]

    try:
        if suffix == ".zip":
            os.makedirs(dest_dir, exist_ok=True)
            with zipfile.ZipFile(file_path, "r") as zip_ref:
                safe_extract_zip(zip_ref, dest_dir)
            return True
        elif suffix == ".7z":
            if HAS_7Z:
                os.makedirs(dest_dir, exist_ok=True)
                with py7zr.SevenZipFile(file_path, mode="r") as archive:
                    safe_extract_7z(archive, dest_dir)
                return True
            else:
                logger.warning(f"Skipping {file_path}: py7zr is not installed.")
                return False
        elif ".tar" in suffixes or suffix in (".tgz", ".tar"):
            os.makedirs(dest_dir, exist_ok=True)
            with tarfile.open(file_path, "r:*") as tar_ref:
                safe_extract_tar(tar_ref, dest_dir)
            return True
        else:
            # We skip single-file compression formats like .gz, .bz2, .xz
            # unless they are part of a tarball.
            logger.debug(f"Unsupported or single-file compression format: {suffix}")
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

    # Supported extensions (refined)
    extensions = {".zip", ".tar", ".tgz", ".7z"}
    # Also support .tar.gz, .tar.bz2, etc.

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
        suffix = file_path.suffix.lower()
        suffixes = [s.lower() for s in file_path.suffixes]

        is_archive = suffix in extensions or ".tar" in suffixes
        if is_archive:
            # Create a destination directory named after the archive (without extension).
            # For multi-suffix archives like *.tar.gz, strip all archive-related suffixes
            # so "archive.tar.gz" becomes "archive_extracted" instead of "archive.tar_extracted".
            archive_suffixes = [
                ".tar.gz",
                ".tar.bz2",
                ".tar.xz",
                ".tgz",
                ".zip",
                ".tar",
                ".7z",
            ]
            filename_lower = file_path.name.lower()
            base_name = file_path.name
            for sfx in archive_suffixes:
                if filename_lower.endswith(sfx):
                    base_name = file_path.name[: -len(sfx)]
                    break
            if not base_name:
                # Fallback to stem in the unlikely event the name is fully stripped.
                base_name = file_path.stem
            dest_folder = file_path.parent / f"{base_name}_extracted"

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
