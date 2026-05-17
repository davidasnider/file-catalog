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


@pytest.mark.asyncio
async def test_run_standalone_judge_retry_and_persist(db_session, test_engine, mocker):
    """
    Test standalone judge's self-healing retry-and-persist path.
    Verify that a failed judge result triggers analyzer retry,
    persists the corrected result/status/version, and syncs FTS.
    """
    from src.scanner import run_standalone_judge
    from src.db.models import Document, AnalysisTask, TaskStatus, DocumentStatus
    from src.core.analyzer_names import SUMMARIZER_NAME
    from src.core.plugin_registry import ANALYZER_REGISTRY
    from unittest.mock import MagicMock
    from sqlmodel import SQLModel

    # Ensure tables are created for our imported models
    async with test_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    # 1. Populate test Document and Task in the SQLite in-memory DB
    doc = Document(
        path="/path/to/test_doc.txt",
        mime_type="text/plain",
        file_hash="dummyhash",
        file_size=100,
        mtime=1.0,
        status=DocumentStatus.COMPLETED,
    )
    db_session.add(doc)
    await db_session.commit()

    task = AnalysisTask(
        document_id=doc.id,
        task_name=SUMMARIZER_NAME,
        plugin_version="1.0",
        status=TaskStatus.COMPLETED,
        result_data='{"summary": "Bad summary that will fail judge", "skipped": false}',
    )
    db_session.add(task)
    await db_session.commit()

    # 2. Patch the async_session_maker in engine and scanner to use our test engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.ext.asyncio import AsyncSession

    mock_maker = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    mocker.patch("src.scanner.async_session_maker", return_value=mock_maker())
    mocker.patch("src.db.engine.async_session_maker", return_value=mock_maker())
    mocker.patch("src.db.engine.init_db", AsyncMock())
    mocker.patch("src.scanner.init_db", AsyncMock())

    # Mock TaskJudge to return:
    # First check: FAILED
    # Second check (after retry): PASSED
    mock_judge_instance = AsyncMock()
    mock_judge_instance.judge_task.side_effect = ["FAILED", "PASSED"]
    mocker.patch("src.core.judge.TaskJudge", return_value=mock_judge_instance)

    # Mock the SummarizerPlugin in registry and its analyze method
    mock_analyzer_instance = AsyncMock()
    mock_analyzer_instance.analyze.return_value = {
        "summary": "This is a corrected, highly accurate summary",
        "skipped": False,
    }
    mock_analyzer_cls = MagicMock(return_value=mock_analyzer_instance)
    mock_analyzer_cls._analyzer_version = "1.9"
    mocker.patch.dict(ANALYZER_REGISTRY, {SUMMARIZER_NAME: mock_analyzer_cls})

    # Mock FTS sync and console input to prevent blocking
    mock_sync_fts = mocker.patch("src.db.fts.sync_document_to_fts", AsyncMock())
    mocker.patch("rich.console.Console", MagicMock())
    mocker.patch("src.scanner.input", return_value="")

    # 3. Run standalone judge
    await run_standalone_judge()

    # 4. Verify results were updated in the DB
    await db_session.refresh(task)

    assert task.status == TaskStatus.COMPLETED
    assert task.plugin_version == "1.9"
    assert "corrected, highly accurate summary" in task.result_data
    assert task.error_message is None

    # Verify analyzer and FTS were invoked
    mock_analyzer_instance.analyze.assert_called_once_with(
        "/path/to/test_doc.txt",
        "text/plain",
        {
            SUMMARIZER_NAME: {
                "summary": "Bad summary that will fail judge",
                "skipped": False,
            }
        },
    )
    mock_sync_fts.assert_called_once()
