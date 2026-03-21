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


@pytest.mark.asyncio
async def test_text_extractor_rtf(tmp_path):
    plugin = TextExtractorPlugin()

    test_file = tmp_path / "test.rtf"
    test_file.write_text("{\\rtf1 This is rich text.}", encoding="utf-8")

    result = await plugin.analyze(str(test_file), "text/rtf", {})

    assert result["extracted"] is True
    assert "This is rich text." in result["text"]


@pytest.mark.asyncio
async def test_text_extractor_mbox(tmp_path):
    import mailbox

    plugin = TextExtractorPlugin()

    test_file = tmp_path / "test.mbox"
    mbox = mailbox.mbox(test_file)
    msg = mailbox.Message()
    msg.set_payload("Hello from mbox.")
    msg["From"] = "test@example.com"
    mbox.add(msg)
    mbox.close()

    result = await plugin.analyze(str(test_file), "application/mbox", {})

    assert result["extracted"] is True
    assert "Hello from mbox." in result["text"]
