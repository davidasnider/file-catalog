from src.scripts.delete_duplicates import (
    compute_sha256,
    delete_duplicates,
    find_duplicates,
)


def test_find_duplicates_invalid_directory(tmp_path):
    """find_duplicates returns None for non-existent or non-directory paths."""
    assert find_duplicates(str(tmp_path / "nonexistent")) is None

    file_path = tmp_path / "regular_file"
    file_path.write_text("not a directory")
    assert find_duplicates(str(file_path)) is None


def test_find_duplicates_cwd_rejected_without_allow_cwd(tmp_path, monkeypatch):
    """CLI refuses to scan Path.cwd() unless --allow-cwd is provided."""
    from unittest.mock import patch
    import sys
    from src.scripts.delete_duplicates import main
    import pytest

    # Change to tmp_path so Path.cwd() would be a valid target
    monkeypatch.chdir(tmp_path)
    args = [sys.argv[0], str(tmp_path)]
    with patch.object(sys, "argv", args):
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 2


def test_find_duplicates_cwd_accepted_with_allow_cwd(tmp_path, monkeypatch):
    """CLI accepts Path.cwd() when --allow-cwd is provided."""
    import sys
    from src.scripts.delete_duplicates import main
    from unittest.mock import patch

    (tmp_path / "a.txt").write_text("content")
    (tmp_path / "b.txt").write_text("content")

    monkeypatch.chdir(tmp_path)
    args = [sys.argv[0], str(tmp_path), "--allow-cwd", "--dry-run"]
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

    # Unique file should not appear in duplicates
    assert compute_sha256(str(unique)) not in hashes

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


def test_main_confirmation_yes(tmp_path, monkeypatch):
    """CLI with --yes flag bypasses confirmation and deletes files."""
    import sys
    from src.scripts.delete_duplicates import main
    from unittest.mock import patch

    f1 = tmp_path / "1.txt"
    f2 = tmp_path / "2.txt"
    f1.write_text("dup")
    f2.write_text("dup")

    args = [sys.argv[0], str(tmp_path), "--yes"]
    with patch.object(sys, "argv", args):
        main()

    assert f1.exists() != f2.exists()  # One was deleted


def test_main_confirmation_no(tmp_path, monkeypatch):
    """CLI interactive prompt 'n' aborts deletion."""
    import sys
    from src.scripts.delete_duplicates import main
    from unittest.mock import patch
    import pytest

    f1 = tmp_path / "1.txt"
    f2 = tmp_path / "2.txt"
    f1.write_text("dup")
    f2.write_text("dup")

    args = [sys.argv[0], str(tmp_path)]
    with patch.object(sys, "argv", args):
        with patch("builtins.input", return_value="n"):
            with pytest.raises(SystemExit) as excinfo:
                main()
            assert excinfo.value.code == 1

    assert f1.exists()
    assert f2.exists()


def test_main_confirmation_y(tmp_path, monkeypatch):
    """CLI interactive prompt 'y' proceeds with deletion."""
    import sys
    from src.scripts.delete_duplicates import main
    from unittest.mock import patch

    f1 = tmp_path / "1.txt"
    f2 = tmp_path / "2.txt"
    f1.write_text("dup")
    f2.write_text("dup")

    args = [sys.argv[0], str(tmp_path)]
    with patch.object(sys, "argv", args):
        with patch("builtins.input", return_value="y"):
            main()

    assert f1.exists() != f2.exists()  # One was deleted


def test_root_directory_rejected_without_allow_root(monkeypatch):
    """CLI refuses to scan filesystem root '/' unless --allow-root is provided."""
    import sys
    from src.scripts.delete_duplicates import main
    from unittest.mock import patch
    import pytest

    # Change cwd away from / so the CWD guard doesn't fire first
    monkeypatch.chdir("/tmp")
    args = [sys.argv[0], "/"]
    with patch.object(sys, "argv", args):
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 2


def test_root_directory_accepted_with_allow_root(monkeypatch):
    """CLI accepts '/' when --allow-root is provided (guard bypassed)."""
    import sys
    from src.scripts.delete_duplicates import main
    from unittest.mock import patch

    monkeypatch.chdir("/tmp")
    args = [sys.argv[0], "/", "--allow-root", "--dry-run"]
    with patch.object(sys, "argv", args):
        with patch("src.scripts.delete_duplicates.find_duplicates", return_value={}):
            # Should not raise SystemExit(2)
            main()
