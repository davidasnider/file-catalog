from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # LLM Provider configuration
    llm_provider: str = "mlx"
    vision_provider: str = "mlx"
    use_cloud_fallback: bool = False
    use_document_ai: bool = False
    llm_model_path: str = "mlx-community/Meta-Llama-3.1-8B-Instruct-4bit"
    vision_model_path: str = "mlx-community/Qwen2.5-VL-7B-Instruct-4bit"

    # API Keys & Cloud Config
    vertex_api_key: str | None = None
    google_cloud_project: str | None = None
    google_cloud_location: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


# Global settings instance
config = Settings()


def update_config_from_cli(**kwargs):
    """Update settings based on CLI arguments"""
    for key, value in kwargs.items():
        if value is not None and hasattr(config, key):
            setattr(config, key, value)
