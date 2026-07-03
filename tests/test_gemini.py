from unittest.mock import patch
from src.llm.gemini import GeminiProvider


def test_gemini_clear_cache():
    with (
        patch("src.llm.gemini.HAS_VERTEX", True),
        patch("src.llm.gemini.genai", create=True),
    ):
        GeminiProvider.clear_cache()
        assert len(GeminiProvider._cache) == 0

        provider1 = GeminiProvider.get_provider(is_vision=False)
        GeminiProvider.get_provider(is_vision=True)
        assert len(GeminiProvider._cache) == 2
        assert GeminiProvider.get_provider(is_vision=False) is provider1

        GeminiProvider.clear_cache()
        assert len(GeminiProvider._cache) == 0
