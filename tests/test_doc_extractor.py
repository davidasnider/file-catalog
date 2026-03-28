import pytest
import shutil
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from src.plugins.text_extractor import TextExtractorPlugin


@pytest.mark.skipif(not shutil.which("antiword"), reason="antiword not installed")
@pytest.mark.asyncio
async def test_antiword_presence():
    """Verify that antiword is installed and in the PATH."""
    assert shutil.which("antiword") is not None


@pytest.mark.asyncio
async def test_text_extractor_doc_mock(tmp_path):
    """Test .doc extraction logic using a mock async subprocess call."""
    plugin = TextExtractorPlugin()

    # Create a dummy .doc file path
    doc_file = tmp_path / "test.doc"
    doc_file.write_text("Binary word garbage")

    # Patch specifically in the plugin's namespace
    with patch(
        "src.plugins.text_extractor.shutil.which", return_value="/usr/bin/antiword"
    ):
        with patch(
            "src.plugins.text_extractor.asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
        ) as mock_exec:
            # Create a mock process object
            mock_proc = MagicMock()
            mock_proc.communicate = AsyncMock(
                return_value=(b"Extracted text from legacy doc", b"")
            )
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc

            result = await plugin.analyze(str(doc_file), "application/msword", {})

            assert result["extracted"] is True
            assert result["text"] == "Extracted text from legacy doc"
            assert result["source"] == "text_extractor"
            mock_exec.assert_called_once()  # Verify it was called


@pytest.mark.asyncio
async def test_text_extractor_doc_missing_antiword(tmp_path):
    """Test that the plugin handles missing antiword gracefully."""
    plugin = TextExtractorPlugin()
    doc_file = tmp_path / "test.doc"
    doc_file.write_text("Binary word garbage")

    with patch("src.plugins.text_extractor.shutil.which", return_value=None):
        result = await plugin.analyze(str(doc_file), "application/msword", {})
        assert result["extracted"] is False
        assert result["text"] == ""


@pytest.mark.asyncio
async def test_text_extractor_doc_timeout(tmp_path):
    """Test that the plugin handles antiword timeouts gracefully."""
    plugin = TextExtractorPlugin()
    doc_file = tmp_path / "test.doc"
    doc_file.write_text("Binary word garbage")

    with patch(
        "src.plugins.text_extractor.shutil.which", return_value="/usr/bin/antiword"
    ):
        # Patch asyncio.wait_for specifically to raise TimeoutError
        with patch(
            "src.plugins.text_extractor.asyncio.wait_for",
            side_effect=asyncio.TimeoutError(),
        ):
            with patch(
                "src.plugins.text_extractor.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
            ) as mock_exec:
                mock_proc = MagicMock()
                mock_proc.kill = MagicMock()
                mock_proc.wait = AsyncMock()
                mock_exec.return_value = mock_proc

                result = await plugin.analyze(str(doc_file), "application/msword", {})

                assert result["extracted"] is False
                assert result["text"] == ""
                mock_proc.kill.assert_called_once()
