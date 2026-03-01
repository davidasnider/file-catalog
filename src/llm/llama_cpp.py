import os
from pathlib import Path
import asyncio
import logging
from contextlib import redirect_stdout, redirect_stderr
from typing import AsyncGenerator
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from src.llm.provider import LLMProvider

try:
    import psutil

    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    from llama_cpp import Llama

    HAS_LLAMA_CPP = True
except ImportError:
    HAS_LLAMA_CPP = False

try:
    from huggingface_hub import hf_hub_download

    HAS_HF_HUB = True
except ImportError:
    HAS_HF_HUB = False

logger = logging.getLogger(__name__)

KNOWN_MODELS = {
    "Llama-3-8B": (
        "QuantFactory/Meta-Llama-3-8B-Instruct-GGUF",
        "Meta-Llama-3-8B-Instruct.Q4_K_M.gguf",
    ),
    "Phi-4-mini": ("unsloth/phi-4-mini-GGUF", "phi-4-mini-Q4_K_M.gguf"),
    "Llava-1.5-7b": ("mys/ggml_llava-v1.5-7b", "ggml-model-q4_k.gguf"),
    "Llava-1.5-7b-mmproj": ("mys/ggml_llava-v1.5-7b", "mmproj-model-f16.gguf"),
}


class LlamaCppProvider(LLMProvider):
    """
    LLM Provider using llama-cpp-python for local inference.
    """

    @classmethod
    def download_model(cls, model_path: str):
        repo_id = None
        filename = None

        # Search for model info in KNOWN_MODELS (case-insensitive)
        model_name_lower = os.path.basename(model_path).lower()
        for key, info in KNOWN_MODELS.items():
            if key.lower() in model_name_lower:
                repo_id, filename = info
                break

        # Special handling for mmproj files if not found by name
        if not repo_id and "mmproj" in model_name_lower:
            repo_id, filename = KNOWN_MODELS["Llava-1.5-7b-mmproj"]

        if not HAS_HF_HUB or not repo_id:
            raise FileNotFoundError(
                f"Model file not found at {model_path} and auto-download not supported for this path."
            )

        logger.warning(
            f"Model file not found at {model_path}. Attempting to download..."
        )
        try:
            Path(model_path).parent.mkdir(parents=True, exist_ok=True)
            downloaded_path = hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                local_dir=str(Path(model_path).parent),
            )

            if downloaded_path != model_path and os.path.exists(downloaded_path):
                os.rename(downloaded_path, model_path)

        except Exception as e:
            logger.error(f"Failed to download model: {e}")
            raise FileNotFoundError(
                f"Model file not found at {model_path} and download failed."
            )

    def __init__(self, model_path: str, n_ctx: int = 4096, n_gpu_layers: int = -1):
        if not HAS_LLAMA_CPP:
            raise ImportError(
                "llama-cpp-python is not installed. Please install it to use LlamaCppProvider."
            )

        if not os.path.exists(model_path):
            self.download_model(model_path)

        logger.info(f"Initializing Llama with model: {model_path}")

        # Detect if we are loading a vision model, we need the mmproj handler
        chat_handler = None
        if "llava" in model_path.lower():
            try:
                from llama_cpp.llama_chat_format import Llava15ChatHandler

                # Assumes mmproj is in the same directory
                mmproj_path = os.path.join(
                    Path(model_path).parent, KNOWN_MODELS["Llava-1.5-7b-mmproj"][1]
                )
                if not os.path.exists(mmproj_path):
                    self.download_model(mmproj_path)
                logger.info(f"Loading Llava Chat Handler with mmproj: {mmproj_path}")
                chat_handler = Llava15ChatHandler(clip_model_path=mmproj_path)
            except ImportError:
                logger.warning("Llava15ChatHandler not found, vision may fail.")

        # Llama cpp output falls back to C-level print streams, suppress them to keep CLI clean
        with open(os.devnull, "w") as fnull:
            with redirect_stdout(fnull), redirect_stderr(fnull):
                self.llm = Llama(
                    model_path=model_path,
                    n_ctx=n_ctx,
                    n_gpu_layers=n_gpu_layers,
                    chat_handler=chat_handler,
                    verbose=False,
                )

        # Dedicated executor to cleanly manage worker threads
        self.executor = ThreadPoolExecutor(max_workers=1)

    def close(self):
        """Cleanup resources and shutdown the executor."""
        if hasattr(self, "executor"):
            self.executor.shutdown(wait=True)
        # Clear out the llama reference to free memory immediately
        if hasattr(self, "llm"):
            del self.llm

    # For async contexts to ensure cleanup
    def __del__(self):
        self.close()

    async def generate(self, prompt: str, **kwargs) -> str:
        """Run Llama generation in a thread pool executor to avoid blocking the event loop."""
        loop = asyncio.get_running_loop()

        # Merge default kwargs with user overrides
        gen_kwargs = {
            "max_tokens": kwargs.get("max_tokens", 1024),
            "temperature": kwargs.get("temperature", 0.7),
            "echo": False,
        }

        if "response_format" in kwargs:
            gen_kwargs["response_format"] = kwargs["response_format"]

        def _run_sync():
            # Always use chat completion since we are using Instruct-tuned models
            chat_kwargs = dict(gen_kwargs)
            if "echo" in chat_kwargs:
                del chat_kwargs["echo"]

            response = self.llm.create_chat_completion(
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt},
                ],
                **chat_kwargs,
            )
            return response["choices"][0]["message"]["content"].strip()

        return await loop.run_in_executor(self.executor, _run_sync)

    async def generate_stream(self, prompt: str, **kwargs) -> AsyncGenerator[str, None]:
        raise NotImplementedError(
            "Streaming not yet implemented for async LlamaCppProvider"
        )

    async def process_image(self, image_path: str, prompt: str, **kwargs) -> str:
        """Run LLaVA image processing in a thread pool executor."""
        import base64
        import mimetypes

        loop = asyncio.get_running_loop()

        gen_kwargs = {
            "max_tokens": kwargs.get("max_tokens", 512),
            "temperature": kwargs.get("temperature", 0.7),
        }

        def _run_sync():
            with open(image_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode("utf-8")

            mime_type, _ = mimetypes.guess_type(image_path)
            if not mime_type:
                mime_type = "image/jpeg"  # Fallback

            image_url = f"data:{mime_type};base64,{encoded_string}"

            response = self.llm.create_chat_completion(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that accurately describes images.",
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": image_url}},
                            {"type": "text", "text": prompt},
                        ],
                    },
                ],
                **gen_kwargs,
            )
            return response["choices"][0]["message"]["content"].strip()

        return await loop.run_in_executor(self.executor, _run_sync)


class ModelManager:
    _cache: OrderedDict[str, LLMProvider] = OrderedDict()

    @classmethod
    def get_provider(cls, model_path: str, n_ctx: int = 4096) -> LLMProvider | str:
        if not HAS_LLAMA_CPP:
            logger.error("LLAMA_CPP not found")
            return "MISSING_LIBRARY"

        logger.info(f"ModelManager.get_provider called for: {model_path}")
        if model_path in cls._cache:
            provider = cls._cache[model_path]
            # If the cached model has a smaller context than requested, we must reload it
            if provider.llm.context_params.n_ctx < n_ctx:
                logger.info(
                    f"Reloading {model_path} with larger context window ({n_ctx})"
                )
                provider.close()
                del cls._cache[model_path]
            else:
                # Move to end (most recently used)
                provider = cls._cache.pop(model_path)
                cls._cache[model_path] = provider
                return provider

        # Check memory before loading
        cls._ensure_memory()

        try:
            provider = LlamaCppProvider(model_path=model_path, n_ctx=n_ctx)
            cls._cache[model_path] = provider
            return provider
        except FileNotFoundError as e:
            logger.error(f"FileNotFoundError in get_provider: {e}")
            return "MISSING_MODEL"
        except ImportError as e:
            logger.error(f"ImportError in get_provider: {e}")
            return "MISSING_LIBRARY"
        except Exception as e:
            logger.error(f"Unexpected error in get_provider: {e}")
            # Always return a sentinel string that the caller recognizes as an error
            return "MISSING_MODEL"

    @classmethod
    def _ensure_memory(cls):
        if not HAS_PSUTIL:
            return
        # Evict least recently used models from the cache if memory is < 2GB available.
        # We intentionally do not call provider.close() here to avoid closing a model
        # that might currently be in use by another coroutine.
        while cls._cache and psutil.virtual_memory().available < 2 * 1024**3:
            model_path, provider = cls._cache.popitem(last=False)
            logger.warning(
                f"Evicting model {model_path} from cache due to low memory "
                f"(available RAM: {psutil.virtual_memory().available / 1024**3:.2f}GB)"
            )


def get_llm_provider(model_path="models/Llama-3-8B.gguf", n_ctx=4096):
    """Global utility for retrieving model instances"""
    return ModelManager.get_provider(model_path, n_ctx=n_ctx)
