import logging
import asyncio
from typing import AsyncGenerator

from src.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

# Module-level lock to serialize all MLX GPU operations.
# Metal cannot handle concurrent command buffer encoders from different
# async tasks dispatched to the thread pool, causing:
#   "A command encoder is already encoding to this command buffer"
_mlx_gpu_lock = asyncio.Lock()

try:
    from mlx_lm import load, generate, stream_generate

    HAS_MLX = True
except ImportError:
    HAS_MLX = False

try:
    import mlx_vlm as _mlx_vlm_check  # noqa: F401

    HAS_MLX_VLM = True
except ImportError:
    HAS_MLX_VLM = False


class MLXProvider(LLMProvider):
    """
    LLM Provider using Apple's MLX (mlx-lm) for native Silicon acceleration.
    """

    def __init__(self, model_path: str, **kwargs):
        self.is_vision = kwargs.get("is_vision", False)

        if self.is_vision:
            if not HAS_MLX_VLM:
                raise ImportError(
                    "mlx-vlm is not installed. Please install it to use MLXProvider for vision."
                )

            logger.info(f"Initializing MLXProvider (Vision) with model: {model_path}")
            try:
                from mlx_vlm import load as vlm_load

                self.model, self.processor = vlm_load(model_path)

                # Patch processor for older LLaVA 1.5 models where transformers'
                # LlavaProcessor doesn't inherit patch_size from the vision config,
                # causing "int // NoneType" in processing_llava.py
                if getattr(self.processor, "patch_size", None) is None:
                    vision_cfg = getattr(self.model.config, "vision_config", None)
                    if vision_cfg:
                        ps = getattr(vision_cfg, "patch_size", None)
                        if ps:
                            self.processor.patch_size = ps
                            logger.info(
                                f"Patched processor.patch_size = {ps} from vision config"
                            )
                if (
                    getattr(self.processor, "vision_feature_select_strategy", None)
                    is None
                ):
                    self.processor.vision_feature_select_strategy = "default"
                    logger.info(
                        "Patched processor.vision_feature_select_strategy = 'default'"
                    )

            except Exception as e:
                logger.error(f"Failed to load MLX VLM model at {model_path}: {e}")
                raise
        else:
            if not HAS_MLX:
                raise ImportError(
                    "mlx-lm is not installed. Please install it to use MLXProvider."
                )

            logger.info(f"Initializing MLXProvider with model: {model_path}")
            try:
                self.model, self.tokenizer = load(model_path)

                if hasattr(self.tokenizer, "apply_chat_template"):
                    self.use_chat_template = True
                else:
                    self.use_chat_template = False

            except Exception as e:
                logger.error(f"Failed to load MLX model at {model_path}: {e}")
                raise

    async def generate(self, prompt: str, **kwargs) -> str:
        """Run MLX generation asynchronously to avoid blocking the event loop."""
        if self.is_vision:
            raise NotImplementedError("Use process_image for vision tasks.")

        loop = asyncio.get_running_loop()

        max_tokens = kwargs.get("max_tokens", 1024)

        def _run_sync():
            # Format prompt if chat template exists
            if self.use_chat_template:
                messages = [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt},
                ]
                formatted_prompt = self.tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True
                )
            else:
                formatted_prompt = prompt

            response = generate(
                self.model,
                self.tokenizer,
                prompt=formatted_prompt,
                max_tokens=max_tokens,
                verbose=False,
            )
            return response.strip()

        async with _mlx_gpu_lock:
            return await loop.run_in_executor(None, _run_sync)

    async def generate_stream(self, prompt: str, **kwargs) -> AsyncGenerator[str, None]:
        """Stream MLX generation asynchronously."""
        if self.is_vision:
            raise NotImplementedError("Use process_image for vision tasks.")

        loop = asyncio.get_running_loop()

        max_tokens = kwargs.get("max_tokens", 1024)

        if self.use_chat_template:
            messages = [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ]
            formatted_prompt = self.tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
        else:
            formatted_prompt = prompt

        # stream_generate in mlx_lm returns an iterator of tokens
        iterator = stream_generate(
            self.model, self.tokenizer, prompt=formatted_prompt, max_tokens=max_tokens
        )

        async with _mlx_gpu_lock:
            while True:
                try:
                    # get next chunk in threadpool to avoid event loop block
                    chunk = await loop.run_in_executor(None, next, iterator)
                    yield chunk
                except StopIteration:
                    break

    async def process_image(self, image_path: str, prompt: str, **kwargs) -> str:
        """Run multimodal (vision) analysis asynchronously using MLX."""
        if not self.is_vision:
            raise Exception("MLXProvider was not initialized as a vision provider.")

        loop = asyncio.get_running_loop()

        max_tokens = kwargs.get("max_tokens", 512)

        def _run_sync():
            from mlx_vlm import generate as vlm_generate
            # MLX-VLM's generate wrapper automatically applies the processor chat template
            # and handles the image passing.

            # Different processors might have different requirements for the prompt
            # but mlx_vlm generate attempts to format it
            try:
                # Based on mlx_vlm docs, we can format chat prompts or just pass the text and image
                # The generate wrapper often accepts standard prompts
                if hasattr(self.processor, "apply_chat_template"):
                    messages = [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image"},
                            ],
                        }
                    ]
                    formatted_prompt = self.processor.apply_chat_template(
                        messages, tokenize=False, add_generation_prompt=True
                    )
                else:
                    formatted_prompt = prompt

                result = vlm_generate(
                    self.model,
                    self.processor,
                    prompt=formatted_prompt,
                    image=image_path,
                    max_tokens=max_tokens,
                    verbose=False,
                )

                # Check if it returned a GenerationResult or just a string
                if hasattr(result, "text"):
                    return result.text.strip()
                return str(result).strip()

            except Exception as e:
                logger.error(f"MLX VLM execution failed: {e}")
                raise

        async with _mlx_gpu_lock:
            return await loop.run_in_executor(None, _run_sync)
