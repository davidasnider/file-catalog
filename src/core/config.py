from pydantic import Field, PositiveInt
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # LLM Provider configuration
    llm_provider: str = "mlx"
    vision_provider: str = "mlx"
    use_cloud_fallback: bool = False
    use_document_ai: bool = False
    llm_model_path: str = "mlx-community/Meta-Llama-3.1-8B-Instruct-4bit"
    vision_model_path: str = "mlx-community/Qwen3.5-397B-A17B-4bit"
    vision_max_pixels: PositiveInt = Field(
        default=1048576,
        gt=0,
        description="Maximum total pixels for vision model inputs to prevent OOM.",
    )

    @property
    def llm_display_name(self) -> str:
        return self.llm_model_path.split("/")[-1]

    @property
    def vision_display_name(self) -> str:
        return self.vision_model_path.split("/")[-1]

    # API Keys & Cloud Config
    vertex_api_key: str | None = None
    google_cloud_project: str | None = None
    google_cloud_location: str | None = "global"
    document_ai_location: str = "us"

    # Infrastructure & Reliability
    max_concurrent: int = 5
    ingest_batch_size: int = 100
    max_retries: int = 3
    log_format: str = "standard"  # "standard" or "json"
    concurrency_limit_ratio: float = 0.5

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
