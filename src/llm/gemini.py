import logging
import asyncio
from typing import AsyncGenerator

from src.llm.provider import LLMProvider
from src.core.config import config

logger = logging.getLogger(__name__)

try:
    from google import genai
    from google.genai import types

    HAS_VERTEX = True
except ImportError:
    HAS_VERTEX = False


class GeminiProvider(LLMProvider):
    """
    LLM Provider using Google Cloud Vertex AI (Gemini Models).
    """

    def __init__(self, is_vision: bool = False):
        if not HAS_VERTEX:
            raise ImportError(
                "google-genai is not installed. "
                "Please install it to use GeminiProvider."
            )

        client_kwargs = {}

        # Prioritize Application Default Credentials (ADC) for Vertex AI (Enterprise)
        if config.google_cloud_project:
            client_kwargs["vertexai"] = True
            client_kwargs["project"] = config.google_cloud_project
            # Gemini 3.1 preview models are currently only accessible via the 'global' region on Vertex AI
            client_kwargs["location"] = config.google_cloud_location or "global"
        # Fallback to pure API Key for Google AI Studio (Consumer)
        elif config.vertex_api_key:
            client_kwargs["api_key"] = config.vertex_api_key
        else:
            logger.warning(
                "No GOOGLE_CLOUD_PROJECT or VERTEX_API_KEY configured for Gemini."
            )

        self.client = genai.Client(**client_kwargs)

        # Map model name based on whether it is a vision task or a text task
        if is_vision:
            # Vertex AI currently exposes Gemini 3.1 multimodal via a specific preview alias
            self.model_name = "gemini-3.1-flash-image-preview"
        else:
            # Standard text and chat
            self.model_name = "gemini-3-flash-preview"

        logger.info(f"Initializing GeminiProvider with model: {self.model_name}")

    async def generate(self, prompt: str, **kwargs) -> str:
        """Run Gemini generation asynchronously."""
        loop = asyncio.get_running_loop()

        generation_config = types.GenerateContentConfig(
            max_output_tokens=kwargs.get("max_tokens", 1024),
            temperature=kwargs.get("temperature", 0.7),
        )

        if "response_format" in kwargs:
            generation_config.response_mime_type = "application/json"

        # run_in_executor helps avoid blocking the event loop with synchronous SDK calls
        def _run_sync():
            response = self.client.models.generate_content(
                model=self.model_name, contents=prompt, config=generation_config
            )
            return response.text.strip()

        return await loop.run_in_executor(None, _run_sync)

    async def generate_stream(self, prompt: str, **kwargs) -> AsyncGenerator[str, None]:
        """Stream the generated response."""
        loop = asyncio.get_running_loop()

        generation_config = types.GenerateContentConfig(
            max_output_tokens=kwargs.get("max_tokens", 1024),
            temperature=kwargs.get("temperature", 0.7),
        )

        # We need an iterator we can yield from asynchronously
        def _run_sync_stream():
            return self.client.models.generate_content_stream(
                model=self.model_name, contents=prompt, config=generation_config
            )

        # Generating the stream iterator
        response_stream = await loop.run_in_executor(None, _run_sync_stream)

        # Yielding chunks without blocking event loop
        while True:
            try:
                chunk = await loop.run_in_executor(None, next, response_stream)
                if chunk.text:
                    yield chunk.text
            except StopIteration:
                break

    async def process_image(self, image_path: str, prompt: str, **kwargs) -> str:
        """Run multimodal (vision) analysis asynchronously using Gemini."""
        loop = asyncio.get_running_loop()

        generation_config = types.GenerateContentConfig(
            max_output_tokens=kwargs.get("max_tokens", 512),
            temperature=kwargs.get("temperature", 0.2),
        )

        def _run_sync():
            with open(image_path, "rb") as image_file:
                # Detect mime type to ensure it's valid
                import mimetypes

                mime_type, _ = mimetypes.guess_type(image_path)
                if not mime_type:
                    mime_type = "image/jpeg"

                image_bytes = image_file.read()
                image_part = types.Part.from_bytes(
                    data=image_bytes, mime_type=mime_type
                )

            response = self.client.models.generate_content(
                model=self.model_name,
                contents=[image_part, prompt],
                config=generation_config,
            )
            return response.text.strip()

        return await loop.run_in_executor(None, _run_sync)
