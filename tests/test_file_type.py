import logging
from unittest.mock import patch
from src.core.file_type import detect_file_type


def test_detect_file_type_mbox_txt_override():
    """
    Test that a .txt file identified as application/mbox by libmagic
    is correctly overridden to text/plain.
    """
    with patch("magic.from_file") as mock_magic, patch("os.path.exists") as mock_exists:
        # Ensure file "exists" for detection logic
        mock_exists.return_value = True
        # Simulate libmagic misidentifying a .txt file as mbox
        mock_magic.return_value = "application/mbox"

        # Test with a .txt extension
        mime_type = detect_file_type("test_file.txt")
        assert mime_type == "text/plain"

        # Test that it DOES NOT override for .mbox extension
        mime_type = detect_file_type("test_file.mbox")
        assert mime_type == "application/mbox"


def test_detect_file_type_missing_file(caplog):
    """Test that missing files return the default fallback and log a warning."""
    with patch("os.path.exists") as mock_exists:
        mock_exists.return_value = False
        with caplog.at_level(logging.WARNING):
            mime_type = detect_file_type("non_existent_file.pdf")
            assert mime_type == "application/octet-stream"
            assert "File not found" in caplog.text


def test_detect_file_type_magic_fallback_to_mimetypes():
    """Test that it falls back to mimetypes if magic returns a generic text/plain."""
    with (
        patch("magic.from_file") as mock_magic,
        patch("os.path.exists") as mock_exists,
        patch("mimetypes.guess_type") as mock_guess,
    ):
        mock_exists.return_value = True
        mock_magic.return_value = "text/plain"
        # Simulate mimetypes having a more specific type for .md
        mock_guess.return_value = ("text/markdown", None)

        mime_type = detect_file_type("README.md")
        assert mime_type == "text/markdown"


def test_detect_file_type_no_extension():
    """Test that files with no extension rely solely on content (libmagic)."""
    with patch("magic.from_file") as mock_magic, patch("os.path.exists") as mock_exists:
        mock_exists.return_value = True
        mock_magic.return_value = "application/pdf"

        mime_type = detect_file_type("some_random_file")
        assert mime_type == "application/pdf"


def test_detect_file_type_magic_error():
    """Test that it handles libmagic exceptions gracefully."""
    with (
        patch("magic.from_file", side_effect=Exception("Magic failed")),
        patch("os.path.exists") as mock_exists,
        patch("mimetypes.guess_type") as mock_guess,
    ):
        mock_exists.return_value = True
        mock_guess.return_value = ("image/png", None)

        mime_type = detect_file_type("test.png")
        assert mime_type == "image/png"
