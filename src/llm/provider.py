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

    @abstractmethod
    async def get_context_window(self) -> int:
        """
        Returns the total context window size (input + output tokens combined)
        supported by the current model.
        """
        pass

    @abstractmethod
    async def get_max_output_tokens(self) -> int:
        """
        Returns the maximum number of output tokens supported by the current model.
        Used for dynamic request sizing.
        """
        pass

    async def get_safe_output_tokens(
        self, prompt: str, chars_per_token: float = 3.5
    ) -> int:
        """
        Returns a safe max_tokens value that accounts for prompt size.

        Estimates prompt token count from character length, then caps output
        tokens so input + output stays within the provider's reported limit.
        Falls back to get_max_output_tokens() when prompt is small enough.

        Args:
            prompt: The full prompt text that will be sent.
            chars_per_token: Rough character-to-token ratio (default 3.5 for English).

        Returns:
            A safe number of output tokens.

        Raises:
            ValueError: If the estimated input prompt length exceeds the total context window.
        """
        total_ctx = await self.get_context_window()
        model_max = await self.get_max_output_tokens()
        estimated_input_tokens = int(len(prompt) / chars_per_token)

        if estimated_input_tokens >= total_ctx:
            raise ValueError(
                f"Estimated prompt tokens ({estimated_input_tokens}) exceeds "
                f"the model's total context window size ({total_ctx}). Prompt must be truncated or chunked."
            )

        safe_output = total_ctx - estimated_input_tokens
        return min(safe_output, model_max)
