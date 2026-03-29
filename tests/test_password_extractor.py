import pytest
import json
from unittest.mock import MagicMock, patch, AsyncMock
from src.plugins.password_extractor import PasswordExtractorPlugin


@pytest.mark.asyncio
async def test_password_extractor_should_run():
    plugin = PasswordExtractorPlugin()

    # Should run if keywords present
    context = {"Router": {"category": "Technical"}}
    assert (
        plugin.should_run("test.txt", "text/plain", context) is False
    )  # No keywords yet

    with patch(
        "src.core.text_utils.get_all_extracted_text",
        return_value="Here is my Password: 123",
    ):
        assert plugin.should_run("test.txt", "text/plain", context) is True


@pytest.mark.asyncio
async def test_password_extractor_success():
    plugin = PasswordExtractorPlugin()

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(
        return_value=json.dumps({"passwords": ["Secret123!", "0:45", "Password"]})
    )

    with patch(
        "src.plugins.password_extractor.get_llm_provider", return_value=mock_llm
    ):
        with patch(
            "src.core.text_utils.get_all_extracted_text",
            return_value="Password: Secret123!",
        ):
            result = await plugin.analyze("test.txt", "text/plain", {})

            # Should have filtered out '0:45' (timestamp) and 'Password' (label)
            assert "Secret123!" in result["passwords"]
            assert "0:45" not in result["passwords"]
            assert "Password" not in result["passwords"]
            assert result["skipped"] is False


@pytest.mark.asyncio
async def test_password_extractor_empty():
    plugin = PasswordExtractorPlugin()

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value=json.dumps({"passwords": []}))

    with patch(
        "src.plugins.password_extractor.get_llm_provider", return_value=mock_llm
    ):
        with patch(
            "src.core.text_utils.get_all_extracted_text",
            return_value="Just some random text",
        ):
            result = await plugin.analyze("test.txt", "text/plain", {})
            assert result["passwords"] == []
            assert result["skipped"] is False
