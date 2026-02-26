import pytest
from src.plugins.ocr_extractor import OCRExtractorPlugin


@pytest.mark.asyncio
async def test_ocr_extractor_skips_non_images():
    plugin = OCRExtractorPlugin()

    result = await plugin.analyze("/fake/document.pdf", "application/pdf", {})

    assert result["skipped"] is True
    assert result["extracted"] is False
    assert result["text"] == ""


# Note: We won't test actual pytesseract OCR execution in standard unit tests
# to avoid hard binary dependencies (tesseract) failing in basic CI runs.
# We test the logic and skip mechanics.
