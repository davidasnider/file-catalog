import pytest
from src.plugins.ocr_confidence_scorer import OCRConfidenceScorerPlugin


@pytest.mark.asyncio
async def test_ocr_confidence_scorer_high_confidence(monkeypatch, tmp_path):
    plugin = OCRConfidenceScorerPlugin()

    # Create a dummy image file
    from PIL import Image

    img = Image.new("RGB", (100, 30), color="white")
    img_path = tmp_path / "test.png"
    img.save(str(img_path))

    # Mock pytesseract.image_to_data to return high-confidence results
    mock_data = {
        "conf": [95, 90, 88, 92, 97, -1],
        "text": ["Hello", "world", "this", "is", "test", ""],
    }

    monkeypatch.setattr(
        "src.plugins.ocr_confidence_scorer.pytesseract.image_to_data",
        lambda img, output_type: mock_data,
    )

    result = await plugin.analyze(str(img_path), "image/png", {})

    assert result["source"] == "ocr_confidence_scorer"
    assert result["total_words"] == 5
    assert result["mean_confidence"] > 80
    assert result["needs_review"] is False
    assert result["low_confidence_words"] == 0


@pytest.mark.asyncio
async def test_ocr_confidence_scorer_low_confidence(monkeypatch, tmp_path):
    plugin = OCRConfidenceScorerPlugin()

    from PIL import Image

    img = Image.new("RGB", (100, 30), color="white")
    img_path = tmp_path / "test.png"
    img.save(str(img_path))

    # Mock low-confidence OCR results
    mock_data = {
        "conf": [30, 20, 45, 15, 50, -1],
        "text": ["blurry", "text", "hard", "to", "read", ""],
    }

    monkeypatch.setattr(
        "src.plugins.ocr_confidence_scorer.pytesseract.image_to_data",
        lambda img, output_type: mock_data,
    )

    result = await plugin.analyze(str(img_path), "image/png", {})

    assert result["needs_review"] is True
    assert result["mean_confidence"] < 60
    assert result["low_confidence_words"] == 5
    assert result["total_words"] == 5


@pytest.mark.asyncio
async def test_ocr_confidence_scorer_no_words(monkeypatch, tmp_path):
    plugin = OCRConfidenceScorerPlugin()

    from PIL import Image

    img = Image.new("RGB", (100, 30), color="white")
    img_path = tmp_path / "test.png"
    img.save(str(img_path))

    # Mock empty OCR results
    mock_data = {
        "conf": [-1, -1],
        "text": ["", ""],
    }

    monkeypatch.setattr(
        "src.plugins.ocr_confidence_scorer.pytesseract.image_to_data",
        lambda img, output_type: mock_data,
    )

    result = await plugin.analyze(str(img_path), "image/png", {})

    assert result["total_words"] == 0
    assert result["needs_review"] is True
    assert result["mean_confidence"] == 0.0


@pytest.mark.asyncio
async def test_ocr_confidence_scorer_should_run():
    plugin = OCRConfidenceScorerPlugin()

    assert plugin.should_run("/photo.jpg", "image/jpeg", {})
    assert plugin.should_run("/scan.png", "image/png", {})
    assert plugin.should_run("/doc.tiff", "image/tiff", {})
    assert plugin.should_run("/img.bmp", "image/bmp", {})

    # Should not run on non-image types
    assert not plugin.should_run("/doc.pdf", "application/pdf", {})
    assert not plugin.should_run("/doc.txt", "text/plain", {})


@pytest.mark.asyncio
async def test_ocr_confidence_scorer_distribution(monkeypatch, tmp_path):
    plugin = OCRConfidenceScorerPlugin()

    from PIL import Image

    img = Image.new("RGB", (100, 30), color="white")
    img_path = tmp_path / "test.png"
    img.save(str(img_path))

    mock_data = {
        "conf": [95, 45, 100, 5, 72, -1],
        "text": ["word1", "word2", "word3", "word4", "word5", ""],
    }

    monkeypatch.setattr(
        "src.plugins.ocr_confidence_scorer.pytesseract.image_to_data",
        lambda img, output_type: mock_data,
    )

    result = await plugin.analyze(str(img_path), "image/png", {})

    dist = result["confidence_distribution"]
    assert dist["0-9"] == 1  # confidence 5
    assert dist["40-49"] == 1  # confidence 45
    assert dist["70-79"] == 1  # confidence 72
    assert dist["90-99"] == 1  # confidence 95
    assert dist["100"] == 1  # confidence 100
