import pytest
from src.plugins.summarizer import SummarizerPlugin


class MockLLM:
    async def generate(self, prompt, **kwargs):
        return "This is a mocked 3-sentence summary of the document."


@pytest.fixture
def mock_get_llm_provider(monkeypatch):
    monkeypatch.setattr(
        "src.plugins.summarizer.get_llm_provider", lambda **kwargs: MockLLM()
    )


@pytest.mark.asyncio
async def test_summarizer_skips_empty_text():
    plugin = SummarizerPlugin()
    result = await plugin.analyze(
        "/fake/doc.pdf", "application/pdf", {"TextExtractor": {"text": ""}}
    )

    assert result["skipped"] is True
    assert result["summary"] == ""


@pytest.mark.asyncio
async def test_summarizer_uses_context_text(mock_get_llm_provider):
    plugin = SummarizerPlugin()

    context = {
        "TextExtractor": {"text": "A full long document text that needs summarizing."}
    }
    result = await plugin.analyze("/fake/doc.pdf", "application/pdf", context)

    assert result["skipped"] is False
    assert result["summary"] == "This is a mocked 3-sentence summary of the document."


@pytest.mark.asyncio
async def test_summarizer_skips_large_text(mock_get_llm_provider):
    plugin = SummarizerPlugin()

    # Generate text > 20,000 chars
    large_text = "A" * 20001
    context = {"TextExtractor": {"text": large_text}}

    result = await plugin.analyze("/fake/doc.pdf", "application/pdf", context)

    assert result["skipped"] is True
    assert result["summary"] == ""
    assert result["reason"] == "text_too_large"
