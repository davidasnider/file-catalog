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
