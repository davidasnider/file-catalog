import asyncio
import pytest
from src.db.models import Document, DocumentStatus, AnalysisTask
from src.scanner import _load_and_queue_existing_docs


@pytest.mark.asyncio
async def test_priority_queueing_order(db_session, tmp_path):
    """
    Verify that _load_and_queue_existing_docs enqueues documents in the correct priority order:
    1. Unprocessed (PENDING, 0 tasks)
    2. Failed (FAILED)
    3. Other (PENDING with tasks)
    """
    # Create test directory and files
    test_dir = tmp_path / "priority_test"
    test_dir.mkdir()

    # 1. Unprocessed file (Zero processing)
    path1 = str(test_dir / "unprocessed.txt")
    with open(path1, "w") as f:
        f.write("unprocessed")
    doc1 = Document(path=path1, status=DocumentStatus.PENDING, file_hash="h1")
    db_session.add(doc1)

    # 2. Failed file
    path2 = str(test_dir / "failed.txt")
    with open(path2, "w") as f:
        f.write("failed")
    doc2 = Document(path=path2, status=DocumentStatus.FAILED, file_hash="h2")
    db_session.add(doc2)

    # 3. Partially processed file (Pending with tasks)
    path3 = str(test_dir / "partial.txt")
    with open(path3, "w") as f:
        f.write("partial")
    doc3 = Document(path=path3, status=DocumentStatus.PENDING, file_hash="h3")
    db_session.add(doc3)

    await db_session.commit()
    await db_session.refresh(doc1)
    await db_session.refresh(doc2)
    await db_session.refresh(doc3)

    # Add a task to doc3 to make it "partially processed"
    task = AnalysisTask(document_id=doc3.id, task_name="test_task", status="PENDING")
    db_session.add(task)
    await db_session.commit()

    # Mock parameters for _load_and_queue_existing_docs
    docs_to_process = []
    queued_docs = set()
    id_to_path = {}
    id_to_mime = {}
    doc_queue = asyncio.Queue()

    from unittest.mock import AsyncMock, MagicMock

    mock_session_cm = AsyncMock()
    mock_session_cm.__aenter__.return_value = db_session
    mock_session_cm.__aexit__.return_value = None
    mock_session_maker = MagicMock(return_value=mock_session_cm)

    # Run the hydration logic
    await _load_and_queue_existing_docs(
        mock_session_maker,
        docs_to_process,
        queued_docs,
        id_to_path,
        id_to_mime,
        doc_queue,
    )

    # Verify queue order
    # Priority 1: doc1 (Unprocessed)
    # Priority 2: doc2 (Failed)
    # Priority 3: doc3 (Partial)

    order = []
    while not doc_queue.empty():
        order.append(doc_queue.get_nowait())

    assert order == [
        doc1.id,
        doc2.id,
        doc3.id,
    ], f"Expected order [{doc1.id}, {doc2.id}, {doc3.id}], but got {order}"
