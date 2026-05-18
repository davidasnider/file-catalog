import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone, timedelta
from sqlmodel import SQLModel, select
from src.db.models import Document, AnalysisTask, TaskStatus, DocumentStatus
from src.scanner import run_standalone_judge
from src.core.analyzer_names import SUMMARIZER_NAME


@pytest.mark.asyncio
async def test_judge_tracking_ordering_and_update(db_session, test_engine, mocker):
    """
    Verify that run_standalone_judge:
    1. Orders tasks by judged_at (NULLS FIRST, then oldest)
    2. Updates judged_at after judging
    """
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.ext.asyncio import AsyncSession

    # 1. Setup DB
    async with test_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    doc = Document(
        path="/test/doc.txt",
        mime_type="text/plain",
        file_hash="hash",
        status=DocumentStatus.COMPLETED,
    )
    db_session.add(doc)
    await db_session.commit()

    # Task 1: Judged recently
    task1 = AnalysisTask(
        document_id=doc.id,
        task_name=SUMMARIZER_NAME,
        status=TaskStatus.COMPLETED,
        result_data='{"summary": "test1"}',
        judged_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    # Task 2: Judged long ago
    task2 = AnalysisTask(
        document_id=doc.id,
        task_name="Task2",
        status=TaskStatus.COMPLETED,
        result_data='{"summary": "test2"}',
        judged_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    # Task 3: Never judged (NULL)
    task3 = AnalysisTask(
        document_id=doc.id,
        task_name="Task3",
        status=TaskStatus.COMPLETED,
        result_data='{"summary": "test3"}',
        judged_at=None,
    )
    db_session.add_all([task1, task2, task3])
    await db_session.commit()

    # 2. Mocking
    mock_maker = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    mocker.patch("src.scanner.async_session_maker", side_effect=mock_maker)
    mocker.patch("src.db.engine.async_session_maker", side_effect=mock_maker)
    mocker.patch("src.db.engine.init_db", AsyncMock())
    mocker.patch("src.scanner.init_db", AsyncMock())

    mock_judge_instance = AsyncMock()
    mock_judge_instance.judge_task.return_value = "PASSED"
    mocker.patch("src.core.judge.TaskJudge", return_value=mock_judge_instance)

    mocker.patch("rich.console.Console", MagicMock())
    mocker.patch("src.scanner.input", return_value="")
    mocker.patch("src.db.fts.sync_document_to_fts", AsyncMock())

    # 3. Run judge
    await run_standalone_judge()

    # 4. Verify Ordering
    # judge_task should have been called in order: Task3 (NULL), Task2 (Oldest), Task1 (Recent)
    calls = mock_judge_instance.judge_task.call_args_list
    assert len(calls) == 3
    assert calls[0].args[0] == "Task3"
    assert calls[1].args[0] == "Task2"
    assert calls[2].args[0] == SUMMARIZER_NAME

    # 5. Verify Updates
    async with mock_maker() as session:
        tasks = (await session.execute(select(AnalysisTask))).scalars().all()
        now = datetime.now(timezone.utc)
        for t in tasks:
            assert t.judged_at is not None
            # Handle potential naive datetime from SQLite
            t_judged = t.judged_at
            if t_judged.tzinfo is None:
                t_judged = t_judged.replace(tzinfo=timezone.utc)
            # Check it was updated to "now" (roughly)
            assert t_judged > now - timedelta(seconds=10)


@pytest.mark.asyncio
async def test_judge_tracking_error_handling(db_session, test_engine, mocker):
    """
    Verify that run_standalone_judge:
    1. Does NOT update judged_at for ERROR verdicts.
    2. Updates judged_at for FAILED verdicts.
    """
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.ext.asyncio import AsyncSession

    # 1. Setup DB
    async with test_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    doc = Document(
        path="/test/doc_error.txt",
        mime_type="text/plain",
        file_hash="hash_err",
        status=DocumentStatus.COMPLETED,
    )
    db_session.add(doc)
    await db_session.commit()

    # Task 1: Will return ERROR
    task_err = AnalysisTask(
        document_id=doc.id,
        task_name="TaskError",
        status=TaskStatus.COMPLETED,
        result_data='{"summary": "err"}',
        judged_at=None,
    )
    # Task 2: Will return FAILED
    task_fail = AnalysisTask(
        document_id=doc.id,
        task_name="TaskFail",
        status=TaskStatus.COMPLETED,
        result_data='{"summary": "fail"}',
        judged_at=None,
    )
    db_session.add_all([task_err, task_fail])
    await db_session.commit()

    # 2. Mocking
    mock_maker = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    mocker.patch("src.scanner.async_session_maker", side_effect=mock_maker)
    mocker.patch("src.db.engine.async_session_maker", side_effect=mock_maker)
    mocker.patch("rich.console.Console", MagicMock())
    mocker.patch("src.scanner.input", return_value="")

    mock_judge_instance = AsyncMock()

    def judge_side_effect(task_name, *args, **kwargs):
        if task_name == "TaskError":
            return "ERROR"
        return "FAILED"

    mock_judge_instance.judge_task.side_effect = judge_side_effect
    mocker.patch("src.core.judge.TaskJudge", return_value=mock_judge_instance)

    # 3. Run judge
    await run_standalone_judge()

    # 4. Verify Updates
    async with mock_maker() as session:
        # TaskError should still be NULL
        res_err = await session.execute(
            select(AnalysisTask).where(AnalysisTask.task_name == "TaskError")
        )
        task_err_db = res_err.scalar_one()
        assert task_err_db.judged_at is None

        # TaskFail should be UPDATED
        res_fail = await session.execute(
            select(AnalysisTask).where(AnalysisTask.task_name == "TaskFail")
        )
        task_fail_db = res_fail.scalar_one()
        assert task_fail_db.judged_at is not None
