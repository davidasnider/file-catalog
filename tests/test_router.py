import pytest
from src.plugins.router import RouterPlugin


@pytest.mark.asyncio
async def test_router_heuristics():
    router = RouterPlugin()

    # Test valid image mime
    res = await router.analyze("/test.jpg", "image/jpeg", {})
    assert res == {"category": "Image", "method": "heuristic"}

    # Test valid code mime
    res = await router.analyze("/script.py", "text/x-python", {})
    assert res == {"category": "Code", "method": "heuristic"}

    # Test code path extension fallback
    res = await router.analyze("/myscript.sh", "", {})
    assert res == {"category": "Code", "method": "heuristic"}


@pytest.mark.asyncio
async def test_router_llm_fallback(monkeypatch):
    router = RouterPlugin()

    class MockLLM:
        async def generate(self, prompt, **kwargs):
            return '```json\n{"category": "Technical"}\n```'

    monkeypatch.setattr(
        "src.plugins.router.get_llm_provider", lambda **kwargs: MockLLM()
    )

    context = {
        "TextExtractor": {"text": "This is a highly complex engineering server log."}
    }
    res = await router.analyze("/unknown.log", "application/octet-stream", context)

    assert res["category"] == "Technical"
    assert res["method"] == "llm"


@pytest.mark.asyncio
async def test_router_llm_fallback_malformed(monkeypatch):
    router = RouterPlugin()

    class MockLLM:
        async def generate(self, prompt, **kwargs):
            return "I am an AI, the category is technical"

    monkeypatch.setattr(
        "src.plugins.router.get_llm_provider", lambda **kwargs: MockLLM()
    )

    context = {"TextExtractor": {"text": "Some text."}}
    res = await router.analyze("/unknown.xyz", "application/octet-stream", context)

    assert res["category"] == "GenericText"
    assert res["method"] == "error_fallback"
