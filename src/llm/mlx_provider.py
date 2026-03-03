import logging
import asyncio
import weakref
from typing import AsyncGenerator

from src.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

# Module-level dictionary to store locks per event loop.
# Using WeakKeyDictionary prevents leaking locks when loops are destroyed.
_mlx_gpu_locks = weakref.WeakKeyDictionary()


def get_mlx_gpu_lock():
    """
    Returns an asyncio.Lock for the current running event loop.
    Lazily creates the lock if it doesn't exist to avoid 'bound to a different event loop' errors.
    """
    loop = asyncio.get_running_loop()
    if loop not in _mlx_gpu_locks:
        _mlx_gpu_locks[loop] = asyncio.Lock()
    return _mlx_gpu_locks[loop]


try:
    from mlx_lm import load, generate, stream_generate
    from mlx_lm.sample_utils import make_sampler, make_logits_processors

    HAS_MLX = True
except ImportError:
    HAS_MLX = False

try:
    from mlx_vlm import load as vlm_load, generate as vlm_generate

    HAS_MLX_VLM = True
except ImportError:
    HAS_MLX_VLM = False


class MLXProvider(LLMProvider):
    """
    LLM Provider using MLX-LM for Apple Silicon acceleration.
    """

    def __init__(self, model_path: str, is_vision: bool = False, **kwargs):
        self.model_path = model_path
        self.is_vision = is_vision
        self.model = None
        self.tokenizer = None
        self.processor = None
        self.use_chat_template = True

        if self.is_vision:
            if not HAS_MLX_VLM:
                raise ImportError(
                    "mlx-vlm is not installed. Please install it to use MLXProvider for vision."
                )

            logger.info(f"Initializing MLXProvider (Vision) with model: {model_path}")
            try:
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
        """Run MLX generation asynchronously."""
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

        def _run_sync():
            sampler = make_sampler(temp=kwargs.get("temperature", 0.0))
            logits_processors = make_logits_processors(
                repetition_penalty=kwargs.get("repetition_penalty", 1.2)
            )

            response = generate(
                self.model,
                self.tokenizer,
                prompt=formatted_prompt,
                max_tokens=max_tokens,
                sampler=sampler,
                logits_processors=logits_processors,
                verbose=False,
            )
            return response.strip()

        async with get_mlx_gpu_lock():
            return await loop.run_in_executor(None, _run_sync)

    async def generate_stream(self, prompt: str, **kwargs) -> AsyncGenerator[str, None]:
        """Stream the generated response."""
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

        async with get_mlx_gpu_lock():
            sampler = make_sampler(temp=kwargs.get("temperature", 0.0))
            logits_processors = make_logits_processors(
                repetition_penalty=kwargs.get("repetition_penalty", 1.2)
            )

            # stream_generate in mlx_lm returns an iterator of tokens
            iterator = stream_generate(
                self.model,
                self.tokenizer,
                prompt=formatted_prompt,
                max_tokens=max_tokens,
                sampler=sampler,
                logits_processors=logits_processors,
            )

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
            # MLX-VLM's generate wrapper automatically applies the processor chat template
            # and handles the image passing.

            # Different processors might have different requirements for the prompt
            # but mlx_vlm generate attempts to format it
            try:
                if hasattr(self.processor, "apply_chat_template"):
                    messages = [
                        {
                            "role": "user",
                            "content": [
                                {"type": "image"},
                                {"type": "text", "text": prompt},
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
                    temperature=kwargs.get("temperature", 0.0),
                    repetition_penalty=kwargs.get("repetition_penalty", 1.2),
                    verbose=False,
                )

                # Check if it returned a GenerationResult or just a string
                if hasattr(result, "text"):
                    return result.text.strip()
                return str(result).strip()

            except Exception as e:
                logger.error(f"MLX VLM execution failed: {e}")
                raise

        async with get_mlx_gpu_lock():
            return await loop.run_in_executor(None, _run_sync)
