import pytest
from src.plugins.duplicate_detector import DuplicateDetectorPlugin


@pytest.mark.asyncio
async def test_duplicate_detector_computes_hash(tmp_path):
    plugin = DuplicateDetectorPlugin()

    test_file = tmp_path / "file_a.txt"
    test_file.write_text("Hello, world!")

    result = await plugin.analyze(str(test_file), "text/plain", {})

    assert result["file_hash"]
    assert len(result["file_hash"]) == 64  # SHA-256 hex digest length
    assert result["source"] == "duplicate_detector"


@pytest.mark.asyncio
async def test_duplicate_detector_same_content_same_hash(tmp_path):
    plugin = DuplicateDetectorPlugin()

    content = "Identical content for duplicate detection."

    file_a = tmp_path / "file_a.txt"
    file_a.write_text(content)

    file_b = tmp_path / "file_b.txt"
    file_b.write_text(content)

    result_a = await plugin.analyze(str(file_a), "text/plain", {})
    result_b = await plugin.analyze(str(file_b), "text/plain", {})

    assert result_a["file_hash"] == result_b["file_hash"]


@pytest.mark.asyncio
async def test_duplicate_detector_different_content_different_hash(tmp_path):
    plugin = DuplicateDetectorPlugin()

    file_a = tmp_path / "file_a.txt"
    file_a.write_text("Content A")

    file_b = tmp_path / "file_b.txt"
    file_b.write_text("Content B")

    result_a = await plugin.analyze(str(file_a), "text/plain", {})
    result_b = await plugin.analyze(str(file_b), "text/plain", {})

    assert result_a["file_hash"] != result_b["file_hash"]


@pytest.mark.asyncio
async def test_duplicate_detector_empty_file(tmp_path):
    plugin = DuplicateDetectorPlugin()

    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("")

    result = await plugin.analyze(str(empty_file), "text/plain", {})

    assert result["file_hash"]
    assert result["source"] == "duplicate_detector"
