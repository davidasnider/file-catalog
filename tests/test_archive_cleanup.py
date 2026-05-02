import sys
import types
import zipfile
import tarfile
import io
from src.scripts.extract_and_cleanup_archives import extract_archive, process_directory

try:
    import py7zr
except ImportError:
    # Provide a dummy py7zr module so tests can patch it even if py7zr isn't installed.
    py7zr = types.ModuleType("py7zr")
    sys.modules["py7zr"] = py7zr

    class SevenZipFile:
        pass

    py7zr.SevenZipFile = SevenZipFile  # type: ignore


def test_extract_zip(tmp_path):
    # Create a dummy zip file
    zip_path = tmp_path / "test.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("file1.txt", "content1")

    dest_dir = tmp_path / "extracted"
    assert extract_archive(zip_path, dest_dir) is True
    assert (dest_dir / "file1.txt").exists()
    assert (dest_dir / "file1.txt").read_text() == "content1"


def test_extract_tar_gz(tmp_path):
    # Create a dummy tar.gz file
    tar_path = tmp_path / "test.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        f1 = tmp_path / "file1.txt"
        f1.write_text("content1")
        tar.add(f1, arcname="file1.txt")

    dest_dir = tmp_path / "extracted_tar"
    assert extract_archive(tar_path, dest_dir) is True
    assert (dest_dir / "file1.txt").exists()
    assert (dest_dir / "file1.txt").read_text() == "content1"


def test_path_traversal_zip(tmp_path):
    # Create a malicious zip file
    zip_path = tmp_path / "malicious.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        # Note: ZipFile.writestr doesn't allow absolute paths or .. easily,
        # but we can simulate it by providing a name with ..
        z.writestr("../outside.txt", "content")

    dest_dir = tmp_path / "safe_extract"
    # Our safe_extract should fail or raise Exception
    assert extract_archive(zip_path, dest_dir) is False


def test_process_directory(tmp_path):
    # Create a zip file in a directory
    zip_path = tmp_path / "test.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("file1.txt", "content1")

    # Run process_directory (non-interactive, so we don't call main)
    # Mocking input would be needed for main()
    process_directory(str(tmp_path), recursive=False, dry_run=False, keep=True)

    assert (tmp_path / "test_extracted" / "file1.txt").exists()
    assert zip_path.exists()  # Kept because keep=True


def test_process_directory_remove(tmp_path):
    # Create a zip file in a directory
    zip_path = tmp_path / "test.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("file1.txt", "content1")

    process_directory(str(tmp_path), recursive=False, dry_run=False, keep=False)

    assert (tmp_path / "test_extracted" / "file1.txt").exists()
    assert not zip_path.exists()  # Removed because keep=False


def test_process_directory_naming_tar_gz(tmp_path):
    # Create a .tar.gz file
    tar_path = tmp_path / "my_archive.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        f1 = tmp_path / "f1.txt"
        f1.write_text("c1")
        tar.add(f1, arcname="f1.txt")

    process_directory(str(tmp_path), recursive=False, dry_run=False, keep=True)
    # Should be my_archive_extracted, NOT my_archive.tar_extracted
    assert (tmp_path / "my_archive_extracted").exists()
    assert (tmp_path / "my_archive_extracted" / "f1.txt").exists()


def test_path_traversal_7z_mocked(tmp_path, mocker):
    # Mock py7zr to simulate a malicious entry
    mock_7z = mocker.Mock()
    mock_file = mocker.Mock()
    mock_file.filename = "../malicious.txt"
    mock_7z.get_files.return_value = [mock_file]

    mocker.patch(
        "py7zr.SevenZipFile",
        return_value=mocker.MagicMock(
            __enter__=lambda x: mock_7z, __exit__=lambda x, *args: None
        ),
    )
    mocker.patch("src.scripts.extract_and_cleanup_archives.HAS_7Z", True)

    archive_path = tmp_path / "test.7z"
    archive_path.write_text("dummy")

    assert extract_archive(archive_path, tmp_path / "out") is False


def test_valid_tar_symlink(tmp_path):
    # Create a tar file with a valid internal symlink
    tar_path = tmp_path / "valid_symlink.tar"
    with tarfile.open(tar_path, "w") as tar:
        # Create a file
        content = b"hello"
        info = tarfile.TarInfo("target.txt")
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))

        # Internal symlink
        symlink_member = tarfile.TarInfo("link.txt")
        symlink_member.type = tarfile.SYMTYPE
        symlink_member.linkname = "target.txt"
        tar.addfile(symlink_member)

    dest_dir = tmp_path / "extracted_valid_tar"
    assert extract_archive(tar_path, dest_dir) is True
    assert (dest_dir / "target.txt").exists()
    assert (dest_dir / "link.txt").is_symlink()


def test_valid_tar_hardlink(tmp_path):
    # Create a tar file with a valid internal hardlink
    tar_path = tmp_path / "valid_hardlink.tar"
    with tarfile.open(tar_path, "w") as tar:
        # Create a file
        content = b"hello"
        info = tarfile.TarInfo("target.txt")
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))

        # Internal hardlink
        hardlink_member = tarfile.TarInfo("hardlink.txt")
        hardlink_member.type = tarfile.LNKTYPE
        hardlink_member.linkname = "target.txt"
        tar.addfile(hardlink_member)

    dest_dir = tmp_path / "extracted_valid_hardlink"
    assert extract_archive(tar_path, dest_dir) is True
    assert (dest_dir / "target.txt").exists()
    assert (dest_dir / "hardlink.txt").exists()


def test_path_traversal_7z_absolute_symlink_mocked(tmp_path, mocker):
    # Mock py7zr to simulate an absolute symlink
    mock_7z = mocker.Mock()
    mock_file = mocker.Mock()
    mock_file.filename = "abs_link"
    mock_file.is_symlink.return_value = True
    mock_file.link_target = "/tmp/outside"
    mock_7z.get_files.return_value = [mock_file]

    mocker.patch(
        "py7zr.SevenZipFile",
        return_value=mocker.MagicMock(
            __enter__=lambda x: mock_7z, __exit__=lambda x, *args: None
        ),
    )
    mocker.patch("src.scripts.extract_and_cleanup_archives.HAS_7Z", True)

    archive_path = tmp_path / "test_abs_link.7z"
    archive_path.write_text("dummy")

    assert extract_archive(archive_path, tmp_path / "out") is False


def test_path_traversal_tar_symlink(tmp_path):
    # Create a malicious tar file with a symlink pointing outside
    tar_path = tmp_path / "malicious_symlink.tar"
    with tarfile.open(tar_path, "w") as tar:
        # Symlink pointing to /tmp (outside dest_dir)
        symlink_member = tarfile.TarInfo("outside_link")
        symlink_member.type = tarfile.SYMTYPE
        symlink_member.linkname = "../../"
        tar.addfile(symlink_member)

    dest_dir = tmp_path / "extracted_tar_symlink"
    # Extraction should fail due to path traversal check
    # Note: We use extract_archive which calls safe_extract_tar
    # If Python 3.12+, it uses 'data' filter. If older, it uses our manual check.
    # Both should block this.
    assert extract_archive(tar_path, dest_dir) is False


def test_path_traversal_tar_absolute_symlink(tmp_path):
    # Create a malicious tar file with an absolute symlink
    tar_path = tmp_path / "malicious_abs_symlink.tar"
    with tarfile.open(tar_path, "w") as tar:
        symlink_member = tarfile.TarInfo("abs_link")
        symlink_member.type = tarfile.SYMTYPE
        symlink_member.linkname = "/etc/passwd"
        tar.addfile(symlink_member)

    dest_dir = tmp_path / "extracted_tar_abs_symlink"
    assert extract_archive(tar_path, dest_dir) is False


def test_path_traversal_tar_hardlink(tmp_path):
    # Create a malicious tar file with a hardlink pointing outside
    tar_path = tmp_path / "malicious_hardlink.tar"
    with tarfile.open(tar_path, "w") as tar:
        hardlink_member = tarfile.TarInfo("outside_hardlink")
        hardlink_member.type = tarfile.LNKTYPE
        hardlink_member.linkname = "../../outside_file"
        tar.addfile(hardlink_member)

    dest_dir = tmp_path / "extracted_tar_hardlink"
    assert extract_archive(tar_path, dest_dir) is False


def test_path_traversal_7z_symlink_mocked(tmp_path, mocker):
    # Mock py7zr to simulate a malicious symlink
    mock_7z = mocker.Mock()
    mock_file = mocker.Mock()
    mock_file.filename = "malicious_link"
    mock_file.is_symlink.return_value = True
    mock_file.link_target = "../../outside"
    mock_7z.get_files.return_value = [mock_file]

    mocker.patch(
        "py7zr.SevenZipFile",
        return_value=mocker.MagicMock(
            __enter__=lambda x: mock_7z, __exit__=lambda x, *args: None
        ),
    )
    mocker.patch("src.scripts.extract_and_cleanup_archives.HAS_7Z", True)

    archive_path = tmp_path / "test_link.7z"
    archive_path.write_text("dummy")

    assert extract_archive(archive_path, tmp_path / "out") is False
