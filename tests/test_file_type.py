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


def test_detect_file_type_normal_mbox():
    """Test that normal mbox files are still identified correctly."""
    with patch("magic.from_file") as mock_magic, patch("os.path.exists") as mock_exists:
        mock_exists.return_value = True
        mock_magic.return_value = "application/mbox"
        mime_type = detect_file_type("inbox.mbox")
        assert mime_type == "application/mbox"
