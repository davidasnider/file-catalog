import pytest
from src.plugins.metadata import MetadataExtractorPlugin


@pytest.mark.asyncio
async def test_metadata_extractor_success(tmp_path):
    plugin = MetadataExtractorPlugin()
    test_file = tmp_path / "test_file.txt"
    test_file.write_text("Hello World!")

    result = await plugin.analyze(str(test_file), "text/plain", {})

    assert "file_size_bytes" in result
    assert result["file_size_bytes"] == 12
    assert "created_at" in result
    assert "modified_at" in result
    assert result["mime_type"] == "text/plain"


@pytest.mark.asyncio
async def test_metadata_extractor_file_not_found():
    plugin = MetadataExtractorPlugin()

    with pytest.raises(Exception, match="Metadata extraction failed:"):
        await plugin.analyze("non_existent_file.txt", "text/plain", {})
