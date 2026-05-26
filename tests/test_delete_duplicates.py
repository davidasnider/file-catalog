import subprocess
import sys
from pathlib import Path

from src.scripts.delete_duplicates import (
    compute_sha256,
    delete_duplicates,
    find_duplicates,
)


def test_compute_sha256(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello world")
    expected = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"  # pragma: allowlist secret
    assert compute_sha256(str(f)) == expected


def test_find_and_delete_duplicates(tmp_path):
    # Setup test files
    dir1 = tmp_path / "dir1"
    dir1.mkdir()

    file_a = dir1 / "a.txt"  # Shortest
    file_a.write_text("duplicate")

    file_b = dir1 / "longer_name.txt"
    file_b.write_text("duplicate")

    subdir = dir1 / "subdir"
    subdir.mkdir()
    file_c = subdir / "nested.txt"
    file_c.write_text("duplicate")

    unique = dir1 / "unique.txt"
    unique.write_text("unique content")

    # 1. Find duplicates
    hashes = find_duplicates(str(dir1))

    # Use compute_sha256 to get the expected hash for the duplicate content
    dup_hash = compute_sha256(str(file_a))
    assert hashes is not None
    assert dup_hash in hashes
    assert len(hashes[dup_hash]) == 3

    # Unique file should not appear in duplicates
    unique_hash = compute_sha256(str(unique))
    assert unique_hash not in hashes

    # 2. Delete duplicates (Dry Run)
    delete_duplicates(hashes, dry_run=True)
    assert file_a.exists()
    assert file_b.exists()
    assert file_c.exists()
    assert unique.exists()

    # 3. Delete duplicates (Real)
    delete_duplicates(hashes, dry_run=False)
    assert file_a.exists()
    assert not file_b.exists()
    assert not file_c.exists()
    assert unique.exists()


def test_find_duplicates_invalid_directory(tmp_path):
    # Non-existent path returns None
    assert find_duplicates(str(tmp_path / "does_not_exist")) is None

    # Regular file (not a directory) returns None
    f = tmp_path / "file.txt"
    f.write_text("hello")
    assert find_duplicates(str(f)) is None


def test_find_duplicates_cwd_rejected_without_allow_cwd():
    result = subprocess.run(
        [sys.executable, "-m", "src.scripts.delete_duplicates", "."],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "--allow-cwd" in result.stderr


def test_find_duplicates_cwd_accepted_with_allow_cwd(tmp_path):
    # Run from the project root; pass tmp_path as target directory using --allow-cwd
    # is not needed here since we're not scanning cwd, but verify the flag is accepted
    # when it IS cwd by setting cwd= and PYTHONPATH to the project root.
    import os

    project_root = str(Path(__file__).resolve().parent.parent)
    env = os.environ.copy()
    env["PYTHONPATH"] = project_root

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.scripts.delete_duplicates",
            ".",
            "--allow-cwd",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env=env,
    )
    assert result.returncode == 0
