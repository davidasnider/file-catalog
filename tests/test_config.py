from src.core.config import Settings, update_config_from_cli, config


def test_settings_defaults():
    settings = Settings()
    assert settings.llm_provider == "openai"
    assert settings.vision_provider == "openai"
    assert settings.vision_max_pixels == 1048576


def test_settings_properties():
    settings = Settings(
        llm_model_path="some/path/to/llm-model",
        vision_model_path="another/path/to/vision-model",
    )
    assert settings.llm_display_name == "llm-model"
    assert settings.vision_display_name == "vision-model"


def test_update_config_from_cli():
    # Save original
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

        # Test invalid attribute is ignored
        update_config_from_cli(non_existent_key="some_value")
        assert not hasattr(config, "non_existent_key")

    finally:
        # Restore
        config.llm_provider = original_provider
        config.max_concurrent = original_max_concurrent
