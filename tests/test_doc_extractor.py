import pytest
import shutil
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from src.plugins.text_extractor import TextExtractorPlugin
from src.core.analyzer_names import TEXT_EXTRACTOR_NAME


@pytest.mark.asyncio
async def test_antiword_presence():
    """Verify that antiword is installed and in the PATH."""
    assert shutil.which("antiword") is not None, (
        "antiword is not installed or not in PATH. "
        "Install antiword to enable .doc extraction."
    )


@pytest.mark.asyncio
async def test_text_extractor_doc_mock(tmp_path):
    """Test .doc extraction logic using a mock async subprocess call."""
    plugin = TextExtractorPlugin()

    # Create a dummy .doc file path
    doc_file = tmp_path / "test.doc"
    doc_file.write_text("Binary word garbage")

    with patch(
        "src.plugins.text_extractor.shutil.which", return_value="/usr/bin/antiword"
    ):
        with patch(
            "src.plugins.text_extractor.asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_proc = MagicMock()
            mock_proc.communicate = AsyncMock(
                return_value=(b"Extracted text from legacy doc", b"")
            )
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc

            result = await plugin.analyze(str(doc_file), "application/msword", {})

            assert result["extracted"] is True
            assert result["text"] == "Extracted text from legacy doc"
            assert result["source"] == TEXT_EXTRACTOR_NAME
            mock_exec.assert_called_once()


@pytest.mark.asyncio
async def test_text_extractor_doc_missing_antiword(tmp_path):
    """Test that the plugin handles missing antiword gracefully by raising ValueError."""
    plugin = TextExtractorPlugin()
    doc_file = tmp_path / "test.doc"
    doc_file.write_text("Binary word garbage")

    with patch("src.plugins.text_extractor.shutil.which", return_value=None):
        with pytest.raises(ValueError, match="No text extracted"):
            await plugin.analyze(str(doc_file), "application/msword", {})


@pytest.mark.asyncio
async def test_text_extractor_doc_timeout(tmp_path):
    """Test that the plugin handles antiword timeouts by raising ValueError."""
    plugin = TextExtractorPlugin()
    doc_file = tmp_path / "test.doc"
    doc_file.write_text("Binary word garbage")

    with patch(
        "src.plugins.text_extractor.shutil.which", return_value="/usr/bin/antiword"
    ):
        with patch(
            "src.plugins.text_extractor.asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_proc = MagicMock()
            mock_proc.kill = MagicMock()
            mock_proc.wait = AsyncMock()
            mock_exec.return_value = mock_proc

            # Patch wait_for to raise TimeoutError when called
            with patch(
                "src.plugins.text_extractor.asyncio.wait_for",
                side_effect=asyncio.TimeoutError,
            ):
                with pytest.raises(ValueError, match="No text extracted"):
                    await plugin.analyze(str(doc_file), "application/msword", {})

                assert mock_proc.kill.called
