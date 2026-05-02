import pytest
from src.plugins.estate_analyzer import EstateAnalyzerPlugin
from src.plugins.text_extractor import TEXT_EXTRACTOR_NAME


class MockLLMJson:
    async def generate(self, prompt, **kwargs):
        # We simulate the LLM returning a slightly messy JSON block
        return '```json\n{"is_estate_document": true, "reasoning": "Mentions a Last Will and Testament."}\n```'


@pytest.fixture
def mock_get_llm_provider(monkeypatch):
    monkeypatch.setattr(
        "src.plugins.estate_analyzer.get_llm_provider", lambda **kwargs: MockLLMJson()
    )


@pytest.mark.asyncio
async def test_estate_analyzer_skips_empty():
    plugin = EstateAnalyzerPlugin()
    result = await plugin.analyze("/fake/doc", "application/pdf", {})

    assert result["skipped"] is True
    assert result["is_estate_document"] is False


@pytest.mark.asyncio
async def test_estate_analyzer_parses_json(mock_get_llm_provider):
    plugin = EstateAnalyzerPlugin()

    context = {TEXT_EXTRACTOR_NAME: {"text": "I hereby declare this my last will..."}}
    result = await plugin.analyze(
        "/fake/will.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        context,
    )

    assert result["skipped"] is False
    assert result["is_estate_document"] is True
    assert "reasoning" in result
