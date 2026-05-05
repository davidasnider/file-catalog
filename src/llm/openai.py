import logging
import base64
import mimetypes
from typing import AsyncGenerator

from openai import AsyncOpenAI
from src.llm.provider import LLMProvider
from src.core.config import config

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    """
    LLM Provider using OpenAI compatible endpoint.
    """

    def __init__(self, model_name: str, **kwargs):
        self.model_name = model_name
        self.client = AsyncOpenAI(
            base_url=config.openai_base_url, api_key=config.openai_api_key
        )
        logger.info(
            f"Initializing OpenAIProvider with model: {self.model_name} at {config.openai_base_url}"
        )

    async def generate(self, prompt: str, **kwargs) -> str:
        """Run generation asynchronously."""
        messages = [{"role": "user", "content": prompt}]

        response_format = None
        rf = kwargs.get("response_format")
        if rf == "json":
            response_format = {"type": "json_object"}
        elif isinstance(rf, dict):
            # Standardize complex formats (like those with "schema") to basic "json_object"
            # for the OpenAI chat completion API.
            response_format = {"type": "json_object"}

        response = await self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            max_tokens=kwargs.get("max_tokens", 1024),
            temperature=kwargs.get("temperature", 0.7),
            response_format=response_format,
        )
        return response.choices[0].message.content.strip()

    async def generate_stream(self, prompt: str, **kwargs) -> AsyncGenerator[str, None]:
        """Stream the generated response."""
        messages = [{"role": "user", "content": prompt}]

        stream = await self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            max_tokens=kwargs.get("max_tokens", 1024),
            temperature=kwargs.get("temperature", 0.7),
            stream=True,
        )

        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def process_image(
        self, image_path: str | list[str], prompt: str, **kwargs
    ) -> str:
        """Run multimodal (vision) analysis asynchronously."""
        from PIL import Image
        import io

        image_paths = [image_path] if isinstance(image_path, str) else image_path

        content = [{"type": "text", "text": prompt}]

        for path in image_paths:
            mime_type, _ = mimetypes.guess_type(path)
            if not mime_type:
                mime_type = "image/jpeg"

            try:
                with Image.open(path) as img:
                    # Convert to RGB (standard for most VLMs)
                    image = img.convert("RGB")

                    # Prevent memory explosion and request payload limits
                    max_pixels = config.vision_max_pixels
                    w, h = image.size
                    if w * h > max_pixels:
                        scale = (max_pixels / (w * h)) ** 0.5
                        new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
                        image.thumbnail(new_size, Image.Resampling.LANCZOS)
                        logger.info(
                            f"Resized image for OpenAI vision processing: {w}x{h} -> {image.size} "
                            f"(Max allowed: {max_pixels} pixels)"
                        )

                    # Encode to base64 from the potentially resized image
                    buffer = io.BytesIO()
                    image.save(buffer, format="JPEG")
                    base64_image = base64.b64encode(buffer.getvalue()).decode("utf-8")

                    content.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            },
                        }
                    )
            except Exception as e:
                logger.error(f"Failed to process image {path} in OpenAIProvider: {e}")
                continue

        if len(content) == 1:
            raise ValueError("No images were successfully processed.")

        messages = [{"role": "user", "content": content}]

        response_format = None
        rf = kwargs.get("response_format")
        if rf == "json":
            response_format = {"type": "json_object"}
        elif isinstance(rf, dict) and "type" in rf:
            response_format = rf

        response = await self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            max_tokens=kwargs.get("max_tokens", 512),
            temperature=kwargs.get("temperature", 0.2),
            response_format=response_format,
        )
        return response.choices[0].message.content.strip()
