from abc import ABC, abstractmethod
from typing import AsyncGenerator


class LLMProvider(ABC):
    """
    Abstract interface for all LLM providers.
    """

    @abstractmethod
    async def generate(self, prompt: str, **kwargs) -> str:
        """
        Generate a complete response from the LLM.

        Args:
            prompt: The input text prompt.
            **kwargs: Provider-specific configuration options (e.g., temperature).

        Returns:
            The generated text response.
        """
        pass

    @abstractmethod
    async def generate_stream(self, prompt: str, **kwargs) -> AsyncGenerator[str, None]:
        """
        Stream the response from the LLM.

        Args:
            prompt: str
            **kwargs: Provider-specific configuration options.

        Yields:
            Chunks of the generated text response.
        """
        pass

    @abstractmethod
    async def process_image(self, image_path: str, prompt: str, **kwargs) -> str:
        """
        Process an image with an optional prompt (requires vision-capable models).

        Args:
            image_path: Absolute path to the image.
            prompt: Text prompt to accompany the image.
            **kwargs: Provider-specific configuration options.

        Returns:
            The generated text response.
        """
        pass
