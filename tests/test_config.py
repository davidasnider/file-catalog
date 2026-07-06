import os

import pytest
from pydantic_settings import SettingsConfigDict

from src.core.config import Settings, config, update_config_from_cli


@pytest.fixture
def clean_env(monkeypatch):
    """Ensure environment variables don't interfere with defaults."""
    # We clear known keys (and their TEST_ prefixed variants) to ensure we get defaults
    keys_to_clear = [
        k
        for k in os.environ.keys()
        if k.upper()
        in [
            "LLM_PROVIDER",
            "TEST_LLM_PROVIDER",
            "VISION_PROVIDER",
            "TEST_VISION_PROVIDER",
            "VISION_MAX_PIXELS",
            "TEST_VISION_MAX_PIXELS",
            "MAX_CONCURRENT",
            "TEST_MAX_CONCURRENT",
            "LLM_MODEL_PATH",
            "TEST_LLM_MODEL_PATH",
            "VISION_MODEL_PATH",
            "TEST_VISION_MODEL_PATH",
        ]
    ]
    for key in keys_to_clear:
        monkeypatch.delenv(key, raising=False)


def test_settings_defaults(clean_env):
    # Bypass all environment variables during testing
    class TestSettings(Settings):
        model_config = SettingsConfigDict(env_file=None, env_prefix="TEST_")

    settings = TestSettings(_env_file=None)
    assert settings.llm_provider == "openai"
    assert settings.vision_provider == "openai"
    assert settings.vision_max_pixels == 1048576


def test_settings_properties():
    settings = Settings(
        llm_model_path="some/path/to/llm-model",
        vision_model_path="another/path/to/vision-model",
        _env_file=None,
    )
    assert settings.llm_display_name == "llm-model"
    assert settings.vision_display_name == "vision-model"


def test_update_config_from_cli():
    # Mutate the global config directly, saving the original state to restore in the finally block
    original_provider = config.llm_provider
    original_max_concurrent = config.max_concurrent

    try:
        # Test valid update
        update_config_from_cli(llm_provider="test_provider", max_concurrent=10)
        assert config.llm_provider == "test_provider"
        assert config.max_concurrent == 10

        # Test None value is ignored
        update_config_from_cli(llm_provider=None)
        assert config.llm_provider == "test_provider"

        # Test invalid attribute is ignored by the utility function
        update_config_from_cli(non_existent_key="some_value")
        assert not hasattr(config, "non_existent_key")

    finally:
        # Restore manually since we need to mutate the actual global instance to test the logic
        config.llm_provider = original_provider
        config.max_concurrent = original_max_concurrent
