import pytest
from unittest.mock import AsyncMock, patch

from src.core.judge import TaskJudge
from src.core.config import config
from src.core.analyzer_names import SUMMARIZER_NAME


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.get_max_output_tokens.return_value = 1000
    provider.get_context_window.return_value = 4096
    provider.get_safe_output_tokens.return_value = 1000
    return provider


@pytest.fixture
def judge(mock_provider):
    return TaskJudge(provider=mock_provider)


@pytest.mark.asyncio
async def test_judge_disabled(judge):
    with patch.object(config, "judge_enabled", False):
        status = await judge.judge_task("SomeTask", "test.txt", {}, {})
        assert status == "SKIPPED"


@pytest.mark.asyncio
async def test_judge_skipped_task(judge):
    with patch.object(config, "judge_enabled", True):
        status = await judge.judge_task("SomeTask", "test.txt", {"skipped": True}, {})
        assert status == "SKIPPED"


@pytest.mark.asyncio
async def test_judge_execution_error(judge):
    with patch.object(config, "judge_enabled", True):
        with patch.object(
            judge, "_handle_failure", new_callable=AsyncMock
        ) as mock_handle:
            status = await judge.judge_task(
                "SomeTask",
                "test.txt",
                {"status": "FAILED", "error": "test error"},
                {},
            )
            assert status == "FAILED"
            mock_handle.assert_called_once()


@pytest.mark.asyncio
async def test_judge_not_judgeable(judge):
    with patch.object(config, "judge_enabled", True):
        status = await judge.judge_task(
            "UnknownTask", "test.txt", {"status": "COMPLETED"}, {}
        )
        assert status == "SKIPPED"


@pytest.mark.asyncio
async def test_judge_empty_response(judge, mock_provider):
    with patch.object(config, "judge_enabled", True):
        mock_provider.generate.return_value = "invalid json"
        with patch.object(
            judge, "_handle_failure", new_callable=AsyncMock
        ) as mock_handle:
            context = {"TextExtractor": {"text": "some text"}}
            result = {"summary": "some summary"}
            status = await judge.judge_task(
                SUMMARIZER_NAME, "test.txt", result, context
            )
            assert status == "ERROR"
            mock_handle.assert_called_once()


@pytest.mark.asyncio
async def test_judge_provider_error(judge, mock_provider):
    with patch.object(config, "judge_enabled", True):
        mock_provider.generate.side_effect = Exception("API down")
        with patch.object(
            judge, "_handle_failure", new_callable=AsyncMock
        ) as mock_handle:
            context = {"TextExtractor": {"text": "some text"}}
            result = {"summary": "some summary"}
            status = await judge.judge_task(
                SUMMARIZER_NAME, "test.txt", result, context
            )
            assert status == "ERROR"
            mock_handle.assert_called_once()


@pytest.mark.asyncio
async def test_judge_passed(judge, mock_provider):
    with patch.object(config, "judge_enabled", True):
        mock_provider.generate.return_value = '{"accuracy": 5, "coverage": 5, "hallucination_free": 5, "reasoning": "Good"}'
        context = {"TextExtractor": {"text": "some text"}}
        result = {"summary": "some summary"}
        status = await judge.judge_task(SUMMARIZER_NAME, "test.txt", result, context)
        assert status == "PASSED"


@pytest.mark.asyncio
async def test_judge_failed(judge, mock_provider):
    with patch.object(config, "judge_enabled", True):
        mock_provider.generate.return_value = '{"accuracy": 2, "coverage": 2, "hallucination_free": 2, "reasoning": "Bad"}'
        with patch.object(
            judge, "_handle_failure", new_callable=AsyncMock
        ) as mock_handle:
            context = {"TextExtractor": {"text": "some text"}}
            result = {"summary": "some summary"}
            status = await judge.judge_task(
                SUMMARIZER_NAME, "test.txt", result, context
            )
            assert status == "FAILED"
            mock_handle.assert_called_once()


@pytest.mark.asyncio
async def test_judge_missing_scores_fails(judge, mock_provider):
    """A malformed response without required score fields should FAIL, not silently pass."""
    with patch.object(config, "judge_enabled", True):
        mock_provider.generate.return_value = '{"reasoning": "Some analysis"}'
        with patch.object(
            judge, "_handle_failure", new_callable=AsyncMock
        ) as mock_handle:
            context = {"TextExtractor": {"text": "some text"}}
            result = {"summary": "some summary"}
            status = await judge.judge_task(
                SUMMARIZER_NAME, "test.txt", result, context
            )
            assert status == "FAILED"
            mock_handle.assert_called_once()


@pytest.mark.asyncio
async def test_judge_low_coverage_fails(judge, mock_provider):
    """A response with low coverage score (<4) should fail the judge task evaluation."""
    with patch.object(config, "judge_enabled", True):
        mock_provider.generate.return_value = '{"accuracy": 5, "coverage": 2, "hallucination_free": 5, "reasoning": "Good except missing major parts"}'
        with patch.object(
            judge, "_handle_failure", new_callable=AsyncMock
        ) as mock_handle:
            context = {"TextExtractor": {"text": "some text"}}
            result = {"summary": "some summary"}
            status = await judge.judge_task(
                SUMMARIZER_NAME, "test.txt", result, context
            )
            assert status == "FAILED"
            mock_handle.assert_called_once()
