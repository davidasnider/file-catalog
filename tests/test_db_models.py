import pytest
from src.db.models import Document, AnalysisTask, DocumentStatus, TaskStatus


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
