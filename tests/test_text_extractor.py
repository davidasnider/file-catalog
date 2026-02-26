import pytest
from src.plugins.text_extractor import TextExtractorPlugin


@pytest.mark.asyncio
async def test_text_extractor_plain_text(tmp_path):
    plugin = TextExtractorPlugin()

    test_file = tmp_path / "test.txt"
    test_file.write_text("This is a simple text file.")

    result = await plugin.analyze(str(test_file), "text/plain", {})

    assert result["extracted"] is True
    assert result["text"] == "This is a simple text file."
    assert result["source"] == "text_extractor"


@pytest.mark.asyncio
async def test_text_extractor_unsupported():
    plugin = TextExtractorPlugin()
    result = await plugin.analyze("/fake/path.exe", "application/octet-stream", {})

    assert result["extracted"] is False
    assert result["text"] == ""
