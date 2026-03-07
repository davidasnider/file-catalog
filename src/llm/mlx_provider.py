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
    from mlx_vlm import load as vlm_load  # noqa: F401

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
            try:
                import mlx.core as mx
                from PIL import Image

                image = Image.open(image_path).convert("RGB")

                # Build the prompt with <image> placeholder
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

                # Compute expected image token count from vision config
                # ViT produces (num_patches + 1) tokens: patches + CLS token
                # 'default' strategy removes CLS → num_patches features
                # 'full' strategy keeps CLS → num_patches + 1 features
                vision_cfg = getattr(self.model.config, "vision_config", None)
                if vision_cfg:
                    img_size = getattr(vision_cfg, "image_size", 336)
                    patch_sz = getattr(vision_cfg, "patch_size", 14)
                    num_patches = (img_size // patch_sz) ** 2
                    strategy = getattr(
                        self.model.config,
                        "vision_feature_select_strategy",
                        "default",
                    )
                    if strategy == "default":
                        num_image_tokens = num_patches
                    else:
                        num_image_tokens = num_patches + 1
                else:
                    num_image_tokens = 576  # fallback for (336/14)^2

                # Split prompt on <image>, tokenize each part, and insert
                # the correct number of image_token_index tokens between them
                image_token_index = getattr(
                    self.model.config, "image_token_index", 32000
                )
                parts = formatted_prompt.split("<image>")

                # Tokenize each text chunk
                tokenizer = getattr(self.processor, "tokenizer", self.processor)
                chunks = [tokenizer(p).input_ids for p in parts]

                # Build input_ids: chunk[0] + [image_token]*N + chunk[1] + ...
                input_ids = chunks[0]
                for i in range(1, len(chunks)):
                    input_ids += [image_token_index] * num_image_tokens
                    input_ids += chunks[i]

                input_ids_mx = mx.array([input_ids])

                # Process image through the image processor
                image_processor = getattr(self.processor, "image_processor", None)
                if image_processor is not None:
                    import torch

                    pp_result = image_processor.preprocess(images=[image])
                    # preprocess returns {'pixel_values': [tensor(3,H,W)]}
                    pv_list = pp_result.get("pixel_values", pp_result)
                    if isinstance(pv_list, list):
                        stacked = torch.stack(pv_list)
                    else:
                        stacked = pv_list
                    pixel_values_mx = mx.array(stacked.numpy())
                else:
                    # Fallback: use processor directly with PyTorch
                    import torch

                    processed = self.processor(
                        text=formatted_prompt,
                        images=[image],
                        return_tensors="pt",
                    )
                    pixel_values_mx = mx.array(processed["pixel_values"].numpy())

                # Create KV cache for autoregressive generation
                from mlx_vlm.models import cache as vlm_cache

                prompt_cache = vlm_cache.make_prompt_cache(self.model.language_model)

                # First pass: get input embeddings from the full model
                # (processes image through vision tower + projector)
                input_embeds_result = self.model.get_input_embeddings(
                    input_ids_mx, pixel_values_mx
                )
                inputs_embeds = input_embeds_result.inputs_embeds

                # Create causal mask for the prompt
                seq_len = inputs_embeds.shape[1]
                mask = mx.triu(mx.full((seq_len, seq_len), float("-inf")), k=1)

                # Run the language model with the vision-enriched embeddings
                output = self.model.language_model(
                    input_ids_mx,
                    inputs_embeds=inputs_embeds,
                    cache=prompt_cache,
                    mask=mask,
                )
                logits = output.logits if hasattr(output, "logits") else output

                # Greedy decode with KV cache
                generated_tokens = []
                eos_token_id = getattr(
                    self.model.config,
                    "eos_token_id",
                    getattr(tokenizer, "eos_token_id", 2),
                )
                for _ in range(max_tokens):
                    next_token = mx.argmax(logits[:, -1, :], axis=-1)
                    token_id = next_token.item()

                    if token_id == eos_token_id:
                        break

                    generated_tokens.append(token_id)
                    # Subsequent tokens use language model with cache
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
