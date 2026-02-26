import pytest
import asyncio
from typing import Dict, Any

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from src.db.models import Document, AnalysisTask, DocumentStatus, TaskStatus
from src.core.task_engine import TaskEngine
from src.core.plugin_registry import AnalyzerBase, register_analyzer, ANALYZER_REGISTRY

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="function")
def reset_registry():
    ANALYZER_REGISTRY.clear()
    yield
    ANALYZER_REGISTRY.clear()


@pytest.fixture(scope="function")
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
    await engine.dispose()


@pytest.fixture(scope="function")
async def db_session(test_engine):
    async_session = sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session


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

    # Run engine
    engine = TaskEngine(max_concurrent_tasks=2)
    await engine.process_document(doc_id, db_session)

    # Verify document success
    updated_doc = await db_session.get(Document, doc_id)
    assert updated_doc.status == DocumentStatus.COMPLETED

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

    # Run engine
    engine = TaskEngine(max_concurrent_tasks=2)
    await engine.process_document(doc_id, db_session)

    # Verify document marked as failed
    updated_doc = await db_session.get(Document, doc_id)
    assert updated_doc.status == DocumentStatus.FAILED

    # Verify task marked as failed
    from sqlmodel import select

    result = await db_session.execute(
        select(AnalysisTask).where(AnalysisTask.document_id == doc_id)
    )
    tasks = result.scalars().all()

    assert len(tasks) == 1
    assert tasks[0].status == TaskStatus.FAILED
    assert "Simulated failure" in tasks[0].error_message
