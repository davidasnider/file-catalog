import logging
from src.core.config import config
from src.llm.provider import LLMProvider

logger = logging.getLogger(__name__)


def get_llm_provider(is_vision: bool = False, **kwargs) -> LLMProvider | str:
    """
    Returns an LLM provider instance based on global configuration.
    Handles cloud fallback logic if enabled.
    """
    provider_type = config.vision_provider if is_vision else config.llm_provider
    model_path = config.vision_model_path if is_vision else config.llm_model_path

    logger.info(
        f"LLM Factory: is_vision={is_vision}, provider={provider_type}, model={model_path}"
    )

    kwargs["is_vision"] = is_vision
    provider = _instantiate_provider(provider_type, model_path, **kwargs)

    # Cloud Fallback Logic
    if isinstance(provider, str) and config.use_cloud_fallback:
        logger.warning(
            f"Local provider '{provider_type}' failed ({provider}). "
            f"Falling back to GeminiProvider since use_cloud_fallback=True."
        )
        try:
            # We lazy import to avoid unnecessary dependencies if not used
            from src.llm.gemini import GeminiProvider

            return GeminiProvider(is_vision=is_vision)
        except ImportError as e:
            logger.error(f"Failed to import GeminiProvider for fallback: {e}")
            return "MISSING_LIBRARY"
        except Exception as e:
            logger.error(f"Failed to instantiate GeminiProvider fallback: {e}")
            return "PROVIDER_INIT_FAILED"

    return provider


def _instantiate_provider(
    provider_type: str, model_path: str, **kwargs
) -> LLMProvider | str:
    if provider_type == "llama_cpp":
        from src.llm.llama_cpp import ModelManager

        return ModelManager.get_provider(model_path, **kwargs)
    elif provider_type == "gemini":
        try:
            from src.llm.gemini import GeminiProvider

            return GeminiProvider(**kwargs)
        except ImportError:
            return "MISSING_LIBRARY"
        except Exception as e:
            logger.error(f"Failed to instantiate GeminiProvider: {e}")
            return "PROVIDER_INIT_FAILED"
    elif provider_type == "mlx":
        try:
            from src.llm.mlx_provider import MLXProvider

            return MLXProvider(model_path, **kwargs)
        except ImportError:
            return "MISSING_LIBRARY"
        except Exception as e:
            logger.error(f"Failed to instantiate MLXProvider: {e}")
            return "PROVIDER_INIT_FAILED"
    else:
        logger.error(f"Unknown provider type: {provider_type}")
        return "UNKNOWN_PROVIDER"
