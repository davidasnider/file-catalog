import pytest
from src.plugins.router import RouterPlugin
from src.core.analyzer_names import TEXT_EXTRACTOR_NAME


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

        async def get_max_output_tokens(self):
            return 4096

        async def get_safe_output_tokens(self, prompt, chars_per_token=3.5):
            return 4096

        async def get_context_window(self):
            return 8192

    monkeypatch.setattr(
        "src.plugins.router.get_llm_provider", lambda **kwargs: MockLLM()
    )

    context = {
        TEXT_EXTRACTOR_NAME: {
            "text": "This is a highly complex engineering server log."
        }
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

        async def get_max_output_tokens(self):
            return 4096

        async def get_safe_output_tokens(self, prompt, chars_per_token=3.5):
            return 4096

        async def get_context_window(self):
            return 8192

    monkeypatch.setattr(
        "src.plugins.router.get_llm_provider", lambda **kwargs: MockLLM()
    )

    context = {TEXT_EXTRACTOR_NAME: {"text": "Some text."}}
    res = await router.analyze("/unknown.xyz", "application/octet-stream", context)

    assert res["category"] == "GenericText"
    assert res["method"] == "error_fallback"


def test_apply_heuristics_edge_cases():
    router = RouterPlugin()

    # Test video and audio mimes
    assert router._apply_heuristics("video/mp4", "/some/file.mp4") == "Video"
    assert router._apply_heuristics("audio/mpeg", "/some/file.mp3") == "Audio"

    # Test empty mime_type or None (unexpected inputs)
    assert router._apply_heuristics("", "/some/file.txt") is None
    assert router._apply_heuristics(None, "/some/file.txt") is None  # type: ignore
    assert router._apply_heuristics("", "/some/file.py") == "Code"
    assert router._apply_heuristics(None, "/some/file.py") == "Code"  # type: ignore

    # Test unknown mime type with known extension
    assert (
        router._apply_heuristics("application/octet-stream", "/some/file.py") == "Code"
    )

    # Test unknown mime type with unknown extension
    assert (
        router._apply_heuristics("application/octet-stream", "/some/file.unknown")
        is None
    )

    # Test code mime types and prefix
    assert router._apply_heuristics("text/x-c", "/some/file.c") == "Code"
    assert router._apply_heuristics("text/x-rust", "/some/file.rs") == "Code"
