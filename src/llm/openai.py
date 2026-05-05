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
        elif isinstance(rf, dict) and "type" in rf:
            # Pass through complex response formats (like json_schema) if the endpoint supports it.
            # Many OpenAI-compatible local servers (vLLM/Ollama) now support basic json_object.
            response_format = rf

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
        image_paths = [image_path] if isinstance(image_path, str) else image_path

        content = [{"type": "text", "text": prompt}]

        for path in image_paths:
            mime_type, _ = mimetypes.guess_type(path)
            if not mime_type:
                mime_type = "image/jpeg"

            with open(path, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode("utf-8")

            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{base64_image}"},
                }
            )

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
