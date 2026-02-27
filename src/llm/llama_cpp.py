import os
from pathlib import Path
import asyncio
import logging
from typing import AsyncGenerator
from src.llm.provider import LLMProvider

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


class LlamaCppProvider(LLMProvider):
    """
    LLM Provider using llama-cpp-python for local inference.
    """

    def __init__(self, model_path: str, n_ctx: int = 4096, n_gpu_layers: int = -1):
        if not HAS_LLAMA_CPP:
            raise ImportError(
                "llama-cpp-python is not installed. Please install it to use LlamaCppProvider."
            )

        if not os.path.exists(model_path):
            if HAS_HF_HUB and "Llama-3-8B" in model_path:
                logger.warning(
                    f"Model file not found at {model_path}. Attempting to download..."
                )
                try:
                    # For MVP we default to a known Quantized Llama-3 GGUF
                    # In a real app, the config would specify the exact repo_id and filename
                    repo_id = "QuantFactory/Meta-Llama-3-8B-Instruct-GGUF"
                    filename = "Meta-Llama-3-8B-Instruct.Q4_K_M.gguf"

                    Path(model_path).parent.mkdir(parents=True, exist_ok=True)
                    downloaded_path = hf_hub_download(
                        repo_id=repo_id,
                        filename=filename,
                        local_dir=str(Path(model_path).parent),
                        local_dir_use_symlinks=False,
                    )

                    # Rename the downloaded file to match our expected generic name
                    if downloaded_path != model_path and os.path.exists(
                        downloaded_path
                    ):
                        os.rename(downloaded_path, model_path)

                except Exception as e:
                    logger.error(f"Failed to download model: {e}")
                    raise FileNotFoundError(
                        f"Model file not found at {model_path} and download failed."
                    )
            else:
                raise FileNotFoundError(f"Model file not found at {model_path}")

        logger.info(f"Initializing Llama with model: {model_path}")
        # Note: In a true async app, this initialization might block the event loop heavily.
        # It's best loaded in an executor or at startup.
        self.llm = Llama(
            model_path=model_path,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,  # -1 for all layers to GPU (if applicable)
            verbose=False,
        )

    async def generate(self, prompt: str, **kwargs) -> str:
        """Run Llama generation in a thread pool executor to avoid blocking the event loop."""
        loop = asyncio.get_running_loop()

        # Merge default kwargs with user overrides
        gen_kwargs = {
            "max_tokens": kwargs.get("max_tokens", 1024),
            "temperature": kwargs.get("temperature", 0.7),
            "echo": False,
        }

        def _run_sync():
            response = self.llm(prompt, **gen_kwargs)
            return response["choices"][0]["text"].strip()

        return await loop.run_in_executor(None, _run_sync)

    async def generate_stream(self, prompt: str, **kwargs) -> AsyncGenerator[str, None]:
        # Steaming async iterator over thread executor requires custom queueing or wrapper,
        # simplified for MVP
        raise NotImplementedError(
            "Streaming not yet implemented for async LlamaCppProvider"
        )

    async def process_image(self, image_path: str, prompt: str, **kwargs) -> str:
        # Requires Llama-cpp compiled with vision support and mmproj model
        raise NotImplementedError(
            "Image processing not implemented for LlamaCppProvider"
        )
