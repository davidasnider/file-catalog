import logging
import asyncio
import os
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
    from mlx_vlm import load as vlm_load

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
        """Run multimodal (vision) analysis asynchronously using MLX.

        Uses the processor directly (with PyTorch tensors) to get properly
        tokenized inputs, then converts to MLX. This bypasses mlx_vlm.generate()
        which has compatibility issues with transformers 5.x.
        """
        if not self.is_vision:
            raise Exception("MLXProvider was not initialized as a vision provider.")

        loop = asyncio.get_running_loop()
        max_tokens = kwargs.get("max_tokens", 512)

        def _run_sync():
            try:
                import mlx.core as mx
                import torch
                from PIL import Image
                from mlx_vlm.models import cache as vlm_cache
                from src.core.config import config

                if not os.path.exists(image_path):
                    raise FileNotFoundError(f"Image not found at {image_path}")

                try:
                    with Image.open(image_path) as img:
                        # Convert to RGB (standard for most VLMs)
                        image = img.convert("RGB")

                        # Prevent memory explosion by ensuring image isn't too large for the VLM sequence.
                        # Sequence length scales linearly with pixels (e.g., Qwen2-VL), but
                        # attention buffers and masks scale O(N^2), leading to OOM on high-res.
                        max_pixels = config.vision_max_pixels
                        w, h = image.size
                        if w * h > max_pixels:
                            # thumbnail preserves aspect ratio while staying within pixel budget
                            scale = (max_pixels / (w * h)) ** 0.5
                            new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
                            image.thumbnail(new_size, Image.Resampling.LANCZOS)
                            logger.info(
                                f"Resized image for vision processing: {w}x{h} -> {image.size} "
                                f"(Max allowed: {max_pixels} pixels)"
                            )
                except Exception as e:
                    logger.error(f"Failed to open/process image {image_path}: {e}")
                    raise ValueError(f"Invalid or corrupt image: {e}") from e

                # Build the prompt with image placeholder
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
                    formatted_prompt = f"USER: <image>\n{prompt} ASSISTANT:"

                # Use the processor directly to get correctly tokenized
                # input_ids with expanded image tokens, pixel_values, and
                # any model-specific extras (e.g., image_grid_thw for Qwen)
                processed = self.processor(
                    text=formatted_prompt,
                    images=[image],
                    return_tensors="pt",
                )

                # Convert all tensors from PyTorch to MLX
                input_ids_mx = mx.array(processed["input_ids"].numpy())
                pixel_values_mx = mx.array(
                    processed["pixel_values"].to(torch.float32).numpy()
                )

                # Collect extra kwargs the model might need
                model_kwargs = {}
                for key in ("image_grid_thw", "video_grid_thw"):
                    if key in processed:
                        model_kwargs[key] = mx.array(processed[key].numpy())

                # Get input embeddings (vision tower + projector + merge)
                input_embeds_result = self.model.get_input_embeddings(
                    input_ids_mx, pixel_values_mx, **model_kwargs
                )
                inputs_embeds = input_embeds_result.inputs_embeds

                # Create KV cache and causal mask
                prompt_cache = vlm_cache.make_prompt_cache(self.model.language_model)
                seq_len = inputs_embeds.shape[1]
                mask = mx.triu(mx.full((seq_len, seq_len), float("-inf")), k=1)

                # Run the language model with vision-enriched embeddings
                output = self.model.language_model(
                    input_ids_mx,
                    inputs_embeds=inputs_embeds,
                    cache=prompt_cache,
                    mask=mask,
                )
                logits = output.logits if hasattr(output, "logits") else output

                # Sampling parameters
                temperature = kwargs.get("temperature", 0.0)
                top_p = kwargs.get("top_p", 1.0)

                # Decode with KV cache
                tokenizer = getattr(self.processor, "tokenizer", self.processor)
                generated_tokens = []
                eos_token_id = getattr(
                    self.model.config,
                    "eos_token_id",
                    getattr(tokenizer, "eos_token_id", 2),
                )
                for _ in range(max_tokens):
                    if temperature > 0:
                        # Temperature-scaled sampling with optional top-p
                        scaled = logits[:, -1, :] / temperature
                        probs = mx.softmax(scaled, axis=-1)
                        if top_p < 1.0:
                            sorted_indices = mx.argsort(probs, axis=-1)[..., ::-1]
                            sorted_probs = mx.take_along_axis(
                                probs, sorted_indices, axis=-1
                            )
                            cumsum = mx.cumsum(sorted_probs, axis=-1)
                            mask = cumsum - sorted_probs > top_p
                            sorted_probs = mx.where(mask, 0.0, sorted_probs)
                            probs = mx.zeros_like(probs)
                            probs = probs.at[
                                mx.arange(probs.shape[0])[:, None],
                                sorted_indices,
                            ].add(sorted_probs)
                        next_token = mx.random.categorical(mx.log(probs + 1e-10))
                    else:
                        # Greedy decode
                        next_token = mx.argmax(logits[:, -1, :], axis=-1)

                    token_id = next_token.item()

                    if token_id == eos_token_id:
                        break

                    generated_tokens.append(token_id)
                    output = self.model.language_model(
                        next_token.reshape(1, 1),
                        cache=prompt_cache,
                    )
                    logits = output.logits if hasattr(output, "logits") else output
                    mx.eval(logits)

                result = tokenizer.decode(generated_tokens, skip_special_tokens=True)
                return result.strip()

            except Exception as e:
                logger.error(f"MLX VLM execution failed: {e}")
                raise

        async with get_mlx_gpu_lock():
            return await loop.run_in_executor(None, _run_sync)


class MLXModelManager:
    _cache = {}

    @classmethod
    def get_provider(cls, model_path: str, is_vision: bool = False, **kwargs):
        cache_key = (model_path, is_vision)
        if cache_key in cls._cache:
            return cls._cache[cache_key]

        provider = MLXProvider(model_path, is_vision=is_vision, **kwargs)
        cls._cache[cache_key] = provider
        return provider
