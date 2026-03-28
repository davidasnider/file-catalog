import pytest
import shutil
from unittest.mock import MagicMock, patch
from src.plugins.text_extractor import TextExtractorPlugin


@pytest.mark.skipif(not shutil.which("antiword"), reason="antiword not installed")
@pytest.mark.asyncio
async def test_antiword_presence():
    """Verify that antiword is installed and in the PATH."""
    assert shutil.which("antiword") is not None


@pytest.mark.asyncio
async def test_text_extractor_doc_mock(tmp_path):
    """Test .doc extraction logic using a mock subprocess call."""
    plugin = TextExtractorPlugin()

    # Create a dummy .doc file path (doesn't need real content for mock test)
    doc_file = tmp_path / "test.doc"
    doc_file.write_text("Binary word garbage")

    with patch("subprocess.run") as mock_run:
        # Mock successful antiword output
        mock_run.return_value = MagicMock(
            stdout="Extracted text from legacy doc", returncode=0
        )

        result = await plugin.analyze(str(doc_file), "application/msword", {})

        assert result["extracted"] is True
        assert result["text"] == "Extracted text from legacy doc"
        assert result["source"] == "text_extractor"
        mock_run.assert_called_with(
            ["antiword", "-t", str(doc_file)],
            capture_output=True,
            text=True,
            check=True,
        )


@pytest.mark.asyncio
async def test_text_extractor_doc_missing_antiword(tmp_path):
    """Test that the plugin handles missing antiword gracefully."""
    plugin = TextExtractorPlugin()
    doc_file = tmp_path / "test.doc"
    doc_file.write_text("Binary word garbage")

    with patch("shutil.which", return_value=None):
        result = await plugin.analyze(str(doc_file), "application/msword", {})
        assert result["extracted"] is False
        assert result["text"] == ""
