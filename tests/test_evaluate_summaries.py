import json
import pytest
from unittest.mock import AsyncMock
from src.db.models import Document, AnalysisTask, TaskStatus
from src.core.analyzer_names import (
    SUMMARIZER_NAME,
    DEEP_SUMMARIZER_NAME,
    TEXT_EXTRACTOR_NAME,
)
from src.scripts.evaluate_summaries import (
    normalize_task_name,
    build_context_from_tasks,
    get_summary_pairs,
)


def test_normalize_task_name():
    """Verify legacy snake_case task names map to canonical PascalCase names."""
    assert normalize_task_name("text_extractor") == TEXT_EXTRACTOR_NAME
    assert normalize_task_name("summarizer") == SUMMARIZER_NAME
    assert normalize_task_name("deep_summarizer") == DEEP_SUMMARIZER_NAME
    assert normalize_task_name("UnknownAnalyzer") == "UnknownAnalyzer"


def test_build_context_from_tasks():
    """Verify context dictionary is reconstructed from completed tasks."""
    t1 = AnalysisTask(
        document_id=1,
        task_name=TEXT_EXTRACTOR_NAME,
        status=TaskStatus.COMPLETED,
        result_data=json.dumps({"text": "Hello world"}),
    )
    t2 = AnalysisTask(
        document_id=1,
        task_name=SUMMARIZER_NAME,
        status=TaskStatus.COMPLETED,
        result_data=json.dumps({"summary": "A greeting"}),
    )
    t3 = AnalysisTask(
        document_id=1,
        task_name="failed_task",
        status=TaskStatus.FAILED,
        result_data=json.dumps({"error": "Failed"}),
    )
    t4 = AnalysisTask(
        document_id=1,
        task_name="invalid_json",
        status=TaskStatus.COMPLETED,
        result_data="invalid json",
    )

    context = build_context_from_tasks([t1, t2, t3, t4])
    assert TEXT_EXTRACTOR_NAME in context
    assert context[TEXT_EXTRACTOR_NAME]["text"] == "Hello world"
    assert SUMMARIZER_NAME in context
    assert context[SUMMARIZER_NAME]["summary"] == "A greeting"
    assert "failed_task" not in context
    assert "invalid_json" not in context


@pytest.mark.asyncio
async def test_get_summary_pairs_empty(db_session):
    """Verify get_summary_pairs returns empty list when no summaries exist."""
    pairs = await get_summary_pairs(db_session, limit=10)
    assert pairs == []


@pytest.mark.asyncio
async def test_get_summary_pairs_zero_limit(db_session):
    """Verify get_summary_pairs handles limit <= 0 gracefully."""
    pairs = await get_summary_pairs(db_session, limit=0)
    assert pairs == []

    pairs_neg = await get_summary_pairs(db_session, limit=-5)
    assert pairs_neg == []


@pytest.mark.asyncio
async def test_get_summary_pairs_batch_fetching(db_session):
    """Verify batch fetching returns correct summary pairs for documents."""
    doc = Document(id=1, path="/test/doc1.txt", file_hash="hash1", file_size=100)
    db_session.add(doc)
    await db_session.commit()

    text_task = AnalysisTask(
        document_id=1,
        task_name=TEXT_EXTRACTOR_NAME,
        status=TaskStatus.COMPLETED,
        result_data=json.dumps({"text": "This is document content."}),
    )
    summary_task = AnalysisTask(
        document_id=1,
        task_name=SUMMARIZER_NAME,
        status=TaskStatus.COMPLETED,
        result_data=json.dumps(
            {"summary": "Short document summary.", "model": "test-model"}
        ),
    )
    db_session.add_all([text_task, summary_task])
    await db_session.commit()

    pairs = await get_summary_pairs(db_session, limit=5)
    assert len(pairs) == 1
    assert pairs[0]["path"] == "/test/doc1.txt"
    assert pairs[0]["source_text"] == "This is document content."
    assert pairs[0]["summary"] == "Short document summary."
    assert pairs[0]["model_used"] == "test-model"


@pytest.mark.asyncio
async def test_get_summary_pairs_prefers_deep_summarizer(db_session):
    """Verify get_summary_pairs prefers DeepSummarizer over Summarizer when both exist."""
    doc = Document(id=2, path="/test/doc2.txt", file_hash="hash2", file_size=200)
    db_session.add(doc)
    await db_session.commit()

    text_task = AnalysisTask(
        document_id=2,
        task_name=TEXT_EXTRACTOR_NAME,
        status=TaskStatus.COMPLETED,
        result_data=json.dumps({"text": "Deep content."}),
    )
    summary_task = AnalysisTask(
        document_id=2,
        task_name=SUMMARIZER_NAME,
        status=TaskStatus.COMPLETED,
        result_data=json.dumps({"summary": "Basic summary.", "model": "basic-model"}),
    )
    deep_task = AnalysisTask(
        document_id=2,
        task_name=DEEP_SUMMARIZER_NAME,
        status=TaskStatus.COMPLETED,
        result_data=json.dumps(
            {"extensive_summary": "Extensive deep summary.", "model": "deep-model"}
        ),
    )
    db_session.add_all([text_task, summary_task, deep_task])
    await db_session.commit()

    pairs = await get_summary_pairs(db_session, limit=5)
    assert len(pairs) == 1
    assert pairs[0]["summary"] == "Extensive deep summary."
    assert pairs[0]["model_used"] == "deep-model"


@pytest.mark.asyncio
async def test_evaluate_pair_success():
    """Verify evaluate_pair parses LLM judgment into structured output."""
    from src.scripts.evaluate_summaries import evaluate_pair

    mock_llm = AsyncMock()
    mock_llm.generate.return_value = json.dumps(
        {
            "accuracy": 5,
            "coverage": 4,
            "hallucination_free": 5,
            "reasoning": "Accurate summary",
        }
    )

    pair = {
        "path": "/test/doc.txt",
        "source_text": "Source text content",
        "summary": "Generated summary",
        "model_used": "mlx-model",
    }

    result = await evaluate_pair(mock_llm, pair)
    assert result["accuracy"] == 5
    assert result["coverage"] == 4
    assert result["hallucination_free"] == 5
    assert result["path"] == "/test/doc.txt"
    assert result["model_used"] == "mlx-model"


@pytest.mark.asyncio
async def test_evaluate_pair_parse_error():
    """Verify evaluate_pair returns error dict when JSON parsing fails."""
    from src.scripts.evaluate_summaries import evaluate_pair

    mock_llm = AsyncMock()
    mock_llm.generate.return_value = "not valid json at all"

    pair = {
        "path": "/test/doc.txt",
        "source_text": "Source text content",
        "summary": "Generated summary",
        "model_used": "mlx-model",
    }

    result = await evaluate_pair(mock_llm, pair)
    assert "error" in result
    assert result["path"] == "/test/doc.txt"


@pytest.mark.asyncio
async def test_evaluate_pair_exception():
    """Verify evaluate_pair handles LLM runtime exceptions gracefully."""
    from src.scripts.evaluate_summaries import evaluate_pair

    mock_llm = AsyncMock()
    mock_llm.generate.side_effect = RuntimeError("API failure")

    pair = {
        "path": "/test/doc.txt",
        "source_text": "Source text content",
        "summary": "Generated summary",
        "model_used": "mlx-model",
    }

    result = await evaluate_pair(mock_llm, pair)
    assert result["error"] == "API failure"
    assert result["path"] == "/test/doc.txt"
