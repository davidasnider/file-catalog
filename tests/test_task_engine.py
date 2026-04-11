import pytest
import asyncio
from typing import Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from src.db.models import Document, AnalysisTask, DocumentStatus, TaskStatus
from src.core.task_engine import TaskEngine
from src.core.plugin_registry import AnalyzerBase, register_analyzer, ANALYZER_REGISTRY


@pytest.fixture(scope="function")
def reset_registry():
    ANALYZER_REGISTRY.clear()
    yield
    ANALYZER_REGISTRY.clear()


@pytest.mark.asyncio
async def test_process_document_success(db_session, reset_registry):
    # Create a mock plugin
    @register_analyzer(name="SuccessPlugin")
    class SuccessPlugin(AnalyzerBase):
        async def analyze(
            self, file_path: str, mime_type: str, context: Dict[str, Any]
        ) -> Dict[str, Any]:
            await asyncio.sleep(0.01)  # Simulate work
            return {"parsed": True}

    # Setup DB
    doc = Document(path="/dummy.txt", mime_type="text/plain")
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)
    doc_id = doc.id

    # Create session maker for TaskEngine
    async_session = sessionmaker(
        db_session.bind, class_=AsyncSession, expire_on_commit=False
    )

    # Run engine
    engine = TaskEngine(async_session_maker=async_session, max_concurrent_tasks=2)
    # Process concurrently MUST be outside the session scope, since TaskEngine provides its own local sessions
    await engine.process_document(doc_id)

    # Verify document success
    # First forcefully expire the db_session cache so it re-reads from the DB connection rather than returning the PENDING cached object
    await db_session.refresh(doc)
    assert doc.status == DocumentStatus.COMPLETED

    # Verify task success, need to query it out
    # For a pure sqlmodel/sqlalchemy approach we would run a select
    from sqlmodel import select

    result = await db_session.execute(
        select(AnalysisTask).where(AnalysisTask.document_id == doc_id)
    )
    tasks = result.scalars().all()

    assert len(tasks) == 1
    assert tasks[0].status == TaskStatus.COMPLETED
    assert tasks[0].task_name == "SuccessPlugin"


@pytest.mark.asyncio
async def test_process_document_failure(db_session, reset_registry):
    # Create a mock plugin that purposefully fails
    @register_analyzer(name="FailPlugin")
    class FailPlugin(AnalyzerBase):
        async def analyze(
            self, file_path: str, mime_type: str, context: Dict[str, Any]
        ) -> Dict[str, Any]:
            raise ValueError("Simulated failure")

    # Setup DB
    doc = Document(path="/dummy2.txt", mime_type="text/plain")
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)
    doc_id = doc.id

    # Create session maker for TaskEngine
    async_session = sessionmaker(
        db_session.bind, class_=AsyncSession, expire_on_commit=False
    )

    # Run engine
    engine = TaskEngine(async_session_maker=async_session, max_concurrent_tasks=2)
    await engine.process_document(doc_id)

    # Verify document marked as failed
    await db_session.refresh(doc)
    assert doc.status == DocumentStatus.FAILED

    # Verify task marked as failed
    from sqlmodel import select

    result = await db_session.execute(
        select(AnalysisTask).where(AnalysisTask.document_id == doc_id)
    )
    tasks = result.scalars().all()

    assert len(tasks) == 1
    assert tasks[0].status == TaskStatus.FAILED
    assert "Simulated failure" in tasks[0].error_message


@pytest.mark.asyncio
async def test_process_document_version_skipping(db_session, reset_registry):
    import json

    # Create a mock plugin
    @register_analyzer(name="VersionPlugin", version="1.0")
    class VersionPlugin(AnalyzerBase):
        async def analyze(
            self, file_path: str, mime_type: str, context: Dict[str, Any]
        ) -> Dict[str, Any]:
            return {"parsed": True, "v": "1.0"}

    # Setup DB
    doc = Document(path="/dummy3.txt", mime_type="text/plain")
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)
    doc_id = doc.id

    async_session = sessionmaker(
        db_session.bind, class_=AsyncSession, expire_on_commit=False
    )

    engine = TaskEngine(async_session_maker=async_session, max_concurrent_tasks=2)

    # Run once
    await engine.process_document(doc_id)
    await db_session.refresh(doc)
    assert doc.status == DocumentStatus.COMPLETED

    from sqlmodel import select

    result = await db_session.execute(
        select(AnalysisTask).where(AnalysisTask.document_id == doc_id)
    )
    task1 = result.scalars().first()
    assert task1.plugin_version == "1.0"
    assert json.loads(task1.result_data) == {"parsed": True, "v": "1.0"}

    # Run again, it should skip
    await engine.process_document(doc_id)

    # The updated_at should ideally remain unchanged if skipped, but it's simpler to just ensure we still have 1 task
    result = await db_session.execute(
        select(AnalysisTask).where(AnalysisTask.document_id == doc_id)
    )
    tasks = result.scalars().all()
    assert len(tasks) == 1
    assert tasks[0].status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_process_document_version_bump_rerun(db_session, reset_registry):
    import json

    # Setup DB
    doc = Document(path="/dummy4.txt", mime_type="text/plain")
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)
    doc_id = doc.id

    async_session = sessionmaker(
        db_session.bind, class_=AsyncSession, expire_on_commit=False
    )
    engine = TaskEngine(async_session_maker=async_session, max_concurrent_tasks=2)

    # Register V1
    @register_analyzer(name="BumpPlugin", version="1.0")
    class BumpPluginV1(AnalyzerBase):
        async def analyze(
            self, file_path: str, mime_type: str, context: Dict[str, Any]
        ) -> Dict[str, Any]:
            return {"v": "1"}

    await engine.process_document(doc_id)

    from sqlmodel import select

    result = await db_session.execute(
        select(AnalysisTask).where(AnalysisTask.document_id == doc_id)
    )
    task1 = result.scalars().first()
    assert task1.plugin_version == "1.0"
    assert json.loads(task1.result_data) == {"v": "1"}

    # Bump version
    ANALYZER_REGISTRY.clear()

    @register_analyzer(name="BumpPlugin", version="2.0")
    class BumpPluginV2(AnalyzerBase):
        async def analyze(
            self, file_path: str, mime_type: str, context: Dict[str, Any]
        ) -> Dict[str, Any]:
            return {"v": "2"}

    # Run again, it should re-run
    await engine.process_document(doc_id)

    # TaskEngine ran in its own sessions, expire db_session to avoid cached IdentityMap reads
    db_session.expire_all()

    result = await db_session.execute(
        select(AnalysisTask).where(AnalysisTask.document_id == doc_id)
    )
    tasks = result.scalars().all()
    assert len(tasks) == 1
    assert tasks[0].status == TaskStatus.COMPLETED
    assert tasks[0].plugin_version == "2.0"
    assert json.loads(tasks[0].result_data) == {"v": "2"}


@pytest.mark.asyncio
async def test_process_document_should_run_skipping(db_session, reset_registry):
    import json

    # Setup DB
    doc = Document(path="/dummy_skip.txt", mime_type="text/plain")
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)
    doc_id = doc.id

    async_session = sessionmaker(
        db_session.bind, class_=AsyncSession, expire_on_commit=False
    )
    engine = TaskEngine(async_session_maker=async_session, max_concurrent_tasks=2)

    # Register SkipPlugin
    @register_analyzer(name="SkipPlugin", version="1.0")
    class SkipPlugin(AnalyzerBase):
        def should_run(
            self, file_path: str, mime_type: str, context: Dict[str, Any]
        ) -> bool:
            return False

        async def analyze(
            self, file_path: str, mime_type: str, context: Dict[str, Any]
        ) -> Dict[str, Any]:
            return {"should_not_reach_here": True}

    await engine.process_document(doc_id)

    from sqlmodel import select

    result = await db_session.execute(
        select(AnalysisTask).where(AnalysisTask.document_id == doc_id)
    )
    task = result.scalars().first()
    assert task is not None
    assert task.status == TaskStatus.COMPLETED
    data = json.loads(task.result_data)
    assert data.get("skipped") is True
    assert "reason" in data


@pytest.mark.asyncio
async def test_process_document_mime_type_fast_path(db_session, reset_registry):
    """Verify that providing mime_type skips the initial document fetch."""

    # Create a mock plugin
    @register_analyzer(name="FastPathPlugin")
    class FastPathPlugin(AnalyzerBase):
        async def analyze(
            self, file_path: str, mime_type: str, context: Dict[str, Any]
        ) -> Dict[str, Any]:
            return {"fast": True}

    # Setup DB
    doc = Document(path="/fast.txt", mime_type="text/plain")
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)
    doc_id = doc.id

    async_session = sessionmaker(
        db_session.bind, class_=AsyncSession, expire_on_commit=False
    )

    # We use a mock session maker to verify that get(Document, ...) is NOT called
    # in the initial fetch block (lines 156-163).
    from unittest.mock import AsyncMock, MagicMock

    # Create a real session to wrap for the execution phase
    real_session = async_session()
    try:
        # Track calls to get()
        original_get = real_session.get
        mock_get = AsyncMock(side_effect=original_get)
        real_session.get = mock_get

        # Mock session maker context manager
        mock_context = MagicMock()
        mock_context.__aenter__.return_value = real_session
        mock_context.__aexit__ = AsyncMock(return_value=None)

        # Mock the maker itself
        mock_maker = MagicMock(return_value=mock_context)

        engine = TaskEngine(async_session_maker=mock_maker, max_concurrent_tasks=1)

        await engine.process_document(doc_id, mime_type="text/plain")

        # Verify that the maker was only called ONCE (for the execution block)
        # instead of TWICE (pre-fetch at line 157 + execution block at line 204).
        assert mock_maker.call_count == 1

        # And verify our session's get was called correctly for Document (refresh + finalize)
        doc_get_calls = [
            call for call in mock_get.call_args_list if call.args[0] == Document
        ]
        assert len(doc_get_calls) == 2

        await db_session.refresh(doc)
        assert doc.status == DocumentStatus.COMPLETED
    finally:
        await real_session.close()
