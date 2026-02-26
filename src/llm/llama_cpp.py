import os
import asyncio
import logging
from typing import AsyncGenerator
from src.llm.provider import LLMProvider

try:
    from llama_cpp import Llama

    HAS_LLAMA_CPP = True
except ImportError:
    HAS_LLAMA_CPP = False

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
