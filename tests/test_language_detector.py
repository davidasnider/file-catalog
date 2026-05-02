import pytest
from src.plugins.language_detector import LanguageDetectorPlugin
from src.plugins.text_extractor import TEXT_EXTRACTOR_NAME


@pytest.mark.asyncio
async def test_language_detector_english():
    plugin = LanguageDetectorPlugin()

    context = {
        TEXT_EXTRACTOR_NAME: {
            "text": "The quick brown fox jumps over the lazy dog. This is a common English sentence used for testing."
        }
    }
    result = await plugin.analyze("/fake/doc.txt", "text/plain", context)

    assert result["language"] == "en"
    assert result["language_name"] == "English"
    assert result["confidence"] > 0.5
    assert result["source"] == "language_detector"


@pytest.mark.asyncio
async def test_language_detector_spanish():
    plugin = LanguageDetectorPlugin()

    context = {
        TEXT_EXTRACTOR_NAME: {
            "text": "El rápido zorro marrón salta sobre el perro perezoso. Esta es una oración común en español."
        }
    }
    result = await plugin.analyze("/fake/doc.txt", "text/plain", context)

    assert result["language"] == "es"
    assert result["language_name"] == "Spanish"
    assert result["confidence"] > 0.5


@pytest.mark.asyncio
async def test_language_detector_french():
    plugin = LanguageDetectorPlugin()

    context = {
        TEXT_EXTRACTOR_NAME: {
            "text": "Le renard brun rapide saute par-dessus le chien paresseux. Ceci est une phrase française courante."
        }
    }
    result = await plugin.analyze("/fake/doc.txt", "text/plain", context)

    assert result["language"] == "fr"
    assert result["language_name"] == "French"


@pytest.mark.asyncio
async def test_language_detector_should_run_skips_short_text():
    plugin = LanguageDetectorPlugin()

    assert not plugin.should_run(
        "/a.txt", "text/plain", {TEXT_EXTRACTOR_NAME: {"text": "Hi"}}
    )

    assert not plugin.should_run(
        "/a.txt", "text/plain", {TEXT_EXTRACTOR_NAME: {"text": ""}}
    )


@pytest.mark.asyncio
async def test_language_detector_should_run_accepts_long_text():
    plugin = LanguageDetectorPlugin()

    assert plugin.should_run(
        "/a.txt",
        "text/plain",
        {
            TEXT_EXTRACTOR_NAME: {
                "text": "This is a sufficiently long text for detection."
            }
        },
    )


@pytest.mark.asyncio
async def test_language_detector_all_languages_list():
    plugin = LanguageDetectorPlugin()

    context = {
        TEXT_EXTRACTOR_NAME: {
            "text": "The quick brown fox jumps over the lazy dog. This is a long English sentence for testing purposes."
        }
    }
    result = await plugin.analyze("/fake/doc.txt", "text/plain", context)

    assert isinstance(result["all_languages"], list)
    assert len(result["all_languages"]) >= 1
    assert "code" in result["all_languages"][0]
    assert "probability" in result["all_languages"][0]
