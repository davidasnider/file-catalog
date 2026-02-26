import pytest
from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import asyncio

from src.db.models import Document, AnalysisTask, DocumentStatus, TaskStatus

# Use an in-memory SQLite database for testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


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
async def test_create_document(db_session):
    doc = Document(path="/tmp/test.pdf", mime_type="application/pdf", file_hash="12345")
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)

    assert doc.id is not None
    assert doc.status == DocumentStatus.PENDING
    assert doc.path == "/tmp/test.pdf"


@pytest.mark.asyncio
async def test_create_analysis_task(db_session):
    doc = Document(path="/tmp/test2.pdf")
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)

    task = AnalysisTask(document_id=doc.id, task_name="OCR")
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    assert task.id is not None
    assert task.status == TaskStatus.PENDING
    assert task.document_id == doc.id

    # Test relationship
    fetched_doc = await db_session.get(Document, doc.id)
    assert doc.id == fetched_doc.id
