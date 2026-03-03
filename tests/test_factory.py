import pytest
from unittest.mock import patch
from src.llm.factory import get_llm_provider
from src.core.config import config


@pytest.fixture
def mock_config():
    """Reset config between tests."""
    original_llm = config.llm_provider
    original_vision = config.vision_provider
    original_fallback = config.use_cloud_fallback
    yield config
    config.llm_provider = original_llm
    config.vision_provider = original_vision
    config.use_cloud_fallback = original_fallback


def test_get_llm_provider_mlx(mock_config):
    config.llm_provider = "mlx"
    with patch("src.llm.mlx_provider.MLXProvider") as mock_mlx:
        get_llm_provider(is_vision=False)
        mock_mlx.assert_called_once()


def test_get_llm_provider_gemini(mock_config):
    config.llm_provider = "gemini"
    with patch("src.llm.gemini.GeminiProvider") as mock_gemini:
        get_llm_provider(is_vision=False)
        mock_gemini.assert_called_once()


def test_get_llm_provider_fallback(mock_config):
    config.llm_provider = "mlx"
    config.use_cloud_fallback = True

    # Simulate MLX initialization failure
    with patch("src.llm.mlx_provider.MLXProvider", side_effect=Exception("MLX fail")):
        with patch("src.llm.gemini.GeminiProvider") as mock_gemini:
            get_llm_provider(is_vision=False)
            # Should fall back to Gemini
            mock_gemini.assert_called_once()


def test_get_llm_provider_no_fallback(mock_config):
    config.llm_provider = "mlx"
    config.use_cloud_fallback = False

    # Simulate MLX initialization failure
    with patch("src.llm.mlx_provider.MLXProvider", side_effect=Exception("MLX fail")):
        with patch("src.llm.gemini.GeminiProvider") as mock_gemini:
            result = get_llm_provider(is_vision=False)
            # Should NOT fall back to Gemini
            mock_gemini.assert_not_called()
            assert result == "MLX fail"
