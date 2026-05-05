import pytest
from unittest.mock import AsyncMock, patch
from src.llm.openai import OpenAIProvider


@pytest.mark.asyncio
async def test_openai_generate():
    with patch("src.llm.openai.AsyncOpenAI") as mock_openai_class:
        mock_client = mock_openai_class.return_value
        mock_client.chat.completions.create = AsyncMock()
        mock_client.chat.completions.create.return_value.choices[
            0
        ].message.content = "Test response"

        provider = OpenAIProvider(model_name="test-model")
        response = await provider.generate("Hello")

        assert response == "Test response"
        mock_client.chat.completions.create.assert_called_once()


@pytest.mark.asyncio
async def test_openai_process_image(tmp_path):
    image_path = tmp_path / "test.jpg"
    image_path.write_bytes(b"fake image data")

    with patch("src.llm.openai.AsyncOpenAI") as mock_openai_class:
        mock_client = mock_openai_class.return_value
        mock_client.chat.completions.create = AsyncMock()
        mock_client.chat.completions.create.return_value.choices[
            0
        ].message.content = "Vision response"

        provider = OpenAIProvider(model_name="test-model")
        response = await provider.process_image(
            str(image_path), "What is in this image?"
        )

        assert response == "Vision response"
        mock_client.chat.completions.create.assert_called_once()
