import pytest
from src.plugins.text_extractor import TextExtractorPlugin
from src.core.analyzer_names import TEXT_EXTRACTOR_NAME


@pytest.mark.asyncio
async def test_text_extractor_plain_text(tmp_path):
    plugin = TextExtractorPlugin()

    test_file = tmp_path / "test.txt"
    test_file.write_text("This is a simple text file.")

    result = await plugin.analyze(str(test_file), "text/plain", {})

    assert result["extracted"] is True
    assert result["text"] == "This is a simple text file."
    assert result["source"] == TEXT_EXTRACTOR_NAME


@pytest.mark.asyncio
async def test_text_extractor_unsupported():
    plugin = TextExtractorPlugin()
    with pytest.raises(ValueError, match="No text extracted"):
        await plugin.analyze("/fake/path.exe", "application/octet-stream", {})


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


@pytest.mark.asyncio
async def test_text_extractor_email_rfc822(tmp_path):
    plugin = TextExtractorPlugin()

    test_file = tmp_path / "test.eml"
    email_content = (
        b"Subject: Test Subject\n"
        b"From: sender@example.com\n"
        b"To: recipient@example.com\n"
        b"Date: Mon, 29 Mar 2026 10:00:00 +0000\n"
        b"\n"
        b"This is the body of the email."
    )
    test_file.write_bytes(email_content)

    result = await plugin.analyze(str(test_file), "message/rfc822", {})

    assert result["extracted"] is True
    assert "Test Subject" in result["text"]
    assert "sender@example.com" in result["text"]
    assert "This is the body of the email." in result["text"]


@pytest.mark.asyncio
async def test_text_extractor_wordperfect(tmp_path):
    plugin = TextExtractorPlugin()

    # Create a dummy WordPerfect file with some printable strings
    test_file = tmp_path / "test.wpd"
    # WordPerfect files often have some binary junk followed by text
    content = b"\x00\x01\x02\x03ThisIsLongEnoughText\x00\x01AndMoreTextHere"
    test_file.write_bytes(content)

    result = await plugin.analyze(str(test_file), "application/vnd.wordperfect", {})

    assert result["extracted"] is True
    assert "ThisIsLongEnoughText" in result["text"]
    assert "AndMoreTextHere" in result["text"]


@pytest.mark.asyncio
async def test_text_extractor_excel_mocked(tmp_path, mocker):
    plugin = TextExtractorPlugin()

    test_file = tmp_path / "test.xls"
    test_file.write_text("dummy")

    # Mock xlrd.open_workbook
    mock_workbook = mocker.Mock()
    mock_sheet = mocker.Mock()
    mock_sheet.name = "Sheet1"
    mock_sheet.nrows = 1
    mock_sheet.row_values.return_value = ["Cell1", "Cell2"]
    mock_workbook.sheets.return_value = [mock_sheet]
    mocker.patch("xlrd.open_workbook", return_value=mock_workbook)

    result = await plugin.analyze(str(test_file), "application/vnd.ms-excel", {})

    assert result["extracted"] is True
    assert "Sheet: Sheet1" in result["text"]
    assert "Cell1 Cell2" in result["text"]


@pytest.mark.asyncio
async def test_text_extractor_powerpoint_mocked(tmp_path, mocker):
    plugin = TextExtractorPlugin()

    test_file = tmp_path / "test.ppt"
    test_file.write_text("dummy")

    # Mock hachoir.parser.createParser and hachoir.metadata.extractMetadata
    mocker.patch(
        "src.plugins.text_extractor.createParser",
        return_value=mocker.MagicMock(
            __enter__=lambda x: x, __exit__=lambda x, *args: None
        ),
    )
    mock_metadata = mocker.Mock()
    mock_metadata.exportPlaintext.return_value = "Mocked PPT metadata text."
    mocker.patch(
        "src.plugins.text_extractor.extractMetadata", return_value=mock_metadata
    )

    result = await plugin.analyze(str(test_file), "application/vnd.ms-powerpoint", {})

    assert result["extracted"] is True
    assert "Mocked PPT metadata text." in result["text"]


@pytest.mark.asyncio
async def test_text_extractor_pptx_mocked(tmp_path, mocker):
    plugin = TextExtractorPlugin()

    test_file = tmp_path / "test.pptx"
    test_file.write_text("dummy")

    # Mock Presentation
    mock_prs = mocker.Mock()
    mock_slide = mocker.Mock()
    mock_shape = mocker.Mock()
    mock_shape.text = "Slide Text"
    mock_slide.shapes = [mock_shape]
    mock_prs.slides = [mock_slide]

    mocker.patch("pptx.Presentation", return_value=mock_prs)

    result = await plugin.analyze(
        str(test_file),
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        {},
    )

    assert result["extracted"] is True
    assert "Slide Text" in result["text"]
