from src.scripts.delete_duplicates import (
    compute_sha256,
    delete_duplicates,
    find_duplicates,
)


def test_find_duplicates_invalid_directory():
    """find_duplicates returns None for non-existent or non-directory paths."""
    assert find_duplicates("/nonexistent/path") is None
    assert find_duplicates("/etc/hostname") is None  # regular file, not directory


def test_find_duplicates_cwd_rejected_without_force(tmp_path, monkeypatch):
    """CLI refuses to scan Path.cwd() unless --force is provided."""
    from unittest.mock import patch
    import sys
    from src.scripts.delete_duplicates import main

    # Change to tmp_path so Path.cwd() would be a valid target
    monkeypatch.chdir(tmp_path)
    args = [sys.argv[0], str(tmp_path)]
    with patch.object(sys, "argv", args):
        try:
            main()
            assert False, "Expected SystemExit"
        except SystemExit as e:
            assert e.code == 2


def test_find_duplicates_cwd_accepted_with_force(tmp_path, monkeypatch, caplog):
    """CLI accepts Path.cwd() when --force is provided."""
    import sys
    from src.scripts.delete_duplicates import main
    from unittest.mock import patch

    (tmp_path / "a.txt").write_text("content")
    (tmp_path / "b.txt").write_text("content")

    monkeypatch.chdir(tmp_path)
    args = [sys.argv[0], str(tmp_path), "--force", "--dry-run"]
    with patch.object(sys, "argv", args):
        # Should not raise SystemExit(2)
        main()  # Runs without error


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
