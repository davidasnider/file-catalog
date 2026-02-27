import os
from pathlib import Path
import asyncio
import logging
from contextlib import redirect_stdout, redirect_stderr
from typing import AsyncGenerator
from concurrent.futures import ThreadPoolExecutor
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

    @classmethod
    def download_model(cls, model_path: str):
        if not HAS_HF_HUB or "Llama-3-8B" not in model_path:
            raise FileNotFoundError(
                f"Model file not found at {model_path} and auto-download not supported for this path."
            )

        logger.warning(
            f"Model file not found at {model_path}. Attempting to download..."
        )
        try:
            repo_id = "QuantFactory/Meta-Llama-3-8B-Instruct-GGUF"
            filename = "Meta-Llama-3-8B-Instruct.Q4_K_M.gguf"

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
        # Note: In a true async app, this initialization might block the event loop heavily.
        # It's best loaded in an executor or at startup.

        # Llama cpp output falls back to C-level print streams, suppress them to keep CLI clean
        with open(os.devnull, "w") as fnull:
            with redirect_stdout(fnull), redirect_stderr(fnull):
                self.llm = Llama(
                    model_path=model_path,
                    n_ctx=n_ctx,
                    n_gpu_layers=n_gpu_layers,  # -1 for all layers to GPU (if applicable)
                    verbose=False,
                )

        # Dedicated executor to cleanly manage worker threads
        self.executor = ThreadPoolExecutor(max_workers=1)

    def close(self):
        """Cleanup resources and shutdown the executor."""
        if hasattr(self, "executor"):
            self.executor.shutdown(wait=True)

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

        def _run_sync():
            response = self.llm(prompt, **gen_kwargs)
            return response["choices"][0]["text"].strip()

        return await loop.run_in_executor(self.executor, _run_sync)

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
