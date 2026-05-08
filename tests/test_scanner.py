import asyncio
import pytest

from sqlmodel import select

from src.db.models import Document, DocumentStatus
from src.scanner import compute_file_hash, ingest_directory


@pytest.fixture
def temp_dir(tmp_path):
    """Provide a temporary directory with some mock files."""
    test_dir = tmp_path / "test_docs"
    test_dir.mkdir()

    file1 = test_dir / "doc1.txt"
    file1.write_text("Hello World!")

    file2 = test_dir / "doc2.txt"
    file2.write_text("Second file")

    return test_dir


def test_compute_file_hash(temp_dir):
    file_path = str(temp_dir / "doc1.txt")
    hash1 = compute_file_hash(file_path)
    assert isinstance(hash1, str)
    assert len(hash1) == 64  # SHA-256


@pytest.mark.asyncio
async def test_ingest_directory_new_files(db_session, temp_dir):
    processed_ids, _ = await ingest_directory(str(temp_dir), db_session)
    assert len(processed_ids) == 2

    result = await db_session.execute(select(Document))
    docs = result.scalars().all()
    assert len(docs) == 2
    assert docs[0].status == DocumentStatus.PENDING
    assert "doc1.txt" in docs[0].path or "doc1.txt" in docs[1].path


@pytest.mark.asyncio
async def test_ingest_directory_modified_files(db_session, temp_dir):
    # First ingestion
    await ingest_directory(str(temp_dir), db_session)

    result = await db_session.execute(select(Document))
    doc1 = result.scalars().first()
    original_hash = doc1.file_hash

    # Modify a file
    with open(doc1.path, "a") as f:
        f.write("Appended content")

    # Second ingestion
    processed_ids, _ = await ingest_directory(str(temp_dir), db_session)
    assert len(processed_ids) == 2

    # Reload mapping
    result = await db_session.execute(select(Document).where(Document.id == doc1.id))
    updated_doc = result.scalars().first()

    assert updated_doc.file_hash != original_hash
    assert updated_doc.status == DocumentStatus.PENDING


@pytest.mark.asyncio
async def test_ingest_directory_unchanged_files_skips_reset(db_session, temp_dir):
    # First ingestion
    await ingest_directory(str(temp_dir), db_session)

    # Mark a document as completed
    result = await db_session.execute(select(Document))
    doc1 = result.scalars().first()
    doc1.status = DocumentStatus.COMPLETED
    await db_session.commit()

    # Second ingestion (no files changed)
    processed_ids, _ = await ingest_directory(str(temp_dir), db_session)
    assert len(processed_ids) == 2

    # Reload mapping
    result = await db_session.execute(select(Document).where(Document.id == doc1.id))
    updated_doc = result.scalars().first()

    # It should STILL be completed, because the hash matched, so we didn't reset it
    assert updated_doc.status == DocumentStatus.COMPLETED


@pytest.mark.asyncio
async def test_ingest_directory_excludes_noise_files(db_session, temp_dir):
    # Add some noise files to the temp directory
    js_file = temp_dir / "script.js"
    js_file.write_text("console.log('hello');")

    py_file = temp_dir / "module.py"
    py_file.write_text("print('hello')")

    css_file = temp_dir / "styles.css"
    css_file.write_text("body { color: red; }")

    font_file = temp_dir / "font.ttf"
    font_file.write_text("dummy font data")

    source_file = temp_dir / "main.c"
    source_file.write_text("int main() { return 0; }")

    xml_file = temp_dir / "data.xml"
    xml_file.write_text("<root><data>hello</data></root>")

    # Ingest directory
    processed_ids, _ = await ingest_directory(str(temp_dir), db_session)

    # Should only process the original 2 .txt files, as .js, .py, .css, and .xml are in IGNORED_EXTENSIONS
    assert len(processed_ids) == 2

    result = await db_session.execute(select(Document))
    docs = result.scalars().all()
    assert len(docs) == 2
    for doc in docs:
        assert "script.js" not in doc.path
        assert "module.py" not in doc.path
        assert "styles.css" not in doc.path
        assert "font.ttf" not in doc.path
        assert "main.c" not in doc.path
        assert "data.xml" not in doc.path
        assert doc.path.endswith(".txt")


@pytest.mark.asyncio
async def test_ingest_directory_with_queue(db_session, temp_dir):
    doc_queue = asyncio.Queue()
    queued_docs = set()
    docs_to_process = []

    # Ingest directory using the queue feature
    processed_ids, _ = await ingest_directory(
        str(temp_dir),
        db_session,
        doc_queue=doc_queue,
        queued_docs=queued_docs,
        docs_to_process=docs_to_process,
    )

    assert len(processed_ids) == 2
    assert len(queued_docs) == 2
    assert len(docs_to_process) == 2

    # Check that items were put on the queue
    item1 = await doc_queue.get()
    item2 = await doc_queue.get()

    assert {item1, item2} == set(processed_ids)


@pytest.mark.asyncio
async def test_run_scanner_chunked_metadata(db_session, temp_dir):
    """
    Verify that the metadata fetching logic (used in run_scanner)
    correctly handles batches larger than SQLite's parameter limit.
    """
    # Create 1200 documents in the DB
    for i in range(1200):
        doc = Document(
            path=f"/path/to/doc{i}.txt",
            mime_type="text/plain",
            file_hash=f"hash{i}",
            file_size=100,
            mtime=1.0,
            status=DocumentStatus.PENDING,
        )
        db_session.add(doc)

    await db_session.commit()

    result = await db_session.execute(select(Document.id))
    ingested_ids = result.scalars().all()
    assert len(ingested_ids) == 1200

    # Simulate the chunking logic from run_scanner
    rows = []
    chunk_size = 500
    for i in range(0, len(ingested_ids), chunk_size):
        chunk = ingested_ids[i : i + chunk_size]
        result = await db_session.execute(
            select(Document.id, Document.path, Document.mime_type).where(
                Document.id.in_(chunk)
            )
        )
        rows.extend(result.all())

    assert len(rows) == 1200
    id_to_path = {row[0]: row[1] for row in rows}
    id_to_mime = {row[0]: row[2] for row in rows}

    assert len(id_to_path) == 1200
    assert id_to_path[ingested_ids[0]] == "/path/to/doc0.txt"
    assert id_to_mime[ingested_ids[1199]] == "text/plain"


@pytest.mark.asyncio
async def test_ingest_directory_atomic_queueing(db_session, temp_dir):
    """Verify that IDs are only enqueued after the DB session is committed."""
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.ext.asyncio import AsyncSession
    from src.core.config import config

    doc_queue = asyncio.Queue()
    queued_docs = set()

    # We use a batch size of 1 for predictable commit points in this test
    original_batch_size = config.ingest_batch_size
    config.ingest_batch_size = 1

    try:
        async_session_maker = sessionmaker(
            db_session.bind, class_=AsyncSession, expire_on_commit=False
        )

        real_put = doc_queue.put

        async def wrapped_put(item):
            # When an item is put in the queue, it MUST be visible to a new session
            async with async_session_maker() as session:
                doc = await session.get(Document, item)
                assert (
                    doc is not None
                ), f"Document {item} was enqueued before it was committed to the DB!"
            await real_put(item)

        doc_queue.put = wrapped_put

        await ingest_directory(
            str(temp_dir), db_session, doc_queue=doc_queue, queued_docs=queued_docs
        )

        assert doc_queue.qsize() == 2
    finally:
        config.ingest_batch_size = original_batch_size


@pytest.mark.asyncio
async def test_run_scanner_handles_missing_files(db_session, temp_dir):
    """Verify that documents whose files are missing on disk are marked as NOT_PRESENT."""
    from src.scanner import _load_and_queue_existing_docs

    # 1. Create a document in the DB
    doc_path = str(temp_dir / "non_existent_file_12345.txt")
    doc = Document(
        path=doc_path,
        mime_type="text/plain",
        file_hash="dummyhash",
        file_size=100,
        mtime=1.0,
        status=DocumentStatus.PENDING,
    )
    db_session.add(doc)
    await db_session.commit()

    # 2. Run the specific startup logic function
    from unittest.mock import AsyncMock, MagicMock

    docs_to_process = []
    queued_docs = set()
    id_to_path = {}
    id_to_mime = {}
    doc_queue = asyncio.Queue()

    # Mocking the session maker context manager cleanly
    mock_session_cm = AsyncMock()
    mock_session_cm.__aenter__.return_value = db_session
    mock_session_cm.__aexit__.return_value = None
    mock_session_maker = MagicMock(return_value=mock_session_cm)

    await _load_and_queue_existing_docs(
        mock_session_maker,
        docs_to_process,
        queued_docs,
        id_to_path,
        id_to_mime,
        doc_queue,
    )

    # 3. Verify the document is now NOT_PRESENT
    # Reload from fresh query to avoid session state issues
    result = await db_session.execute(select(Document).where(Document.id == doc.id))
    updated_doc = result.scalars().first()
    assert updated_doc.status == DocumentStatus.NOT_PRESENT
    assert updated_doc.id not in docs_to_process
    assert doc_queue.empty()


@pytest.mark.asyncio
async def test_ingest_directory_marks_missing_files_as_not_present(
    db_session, temp_dir
):
    """Verify that ingest_directory marks files missing on disk as NOT_PRESENT."""
    # 1. First ingestion to populate DB
    processed_ids, missing_ids = await ingest_directory(str(temp_dir), db_session)
    assert len(processed_ids) == 2
    assert len(missing_ids) == 0

    # 2. Delete one file from disk
    file1_path = temp_dir / "doc1.txt"
    file1_path.unlink()

    # 3. Second ingestion
    processed_ids, missing_ids = await ingest_directory(str(temp_dir), db_session)

    # 4. Verify results
    assert len(processed_ids) == 1
    assert len(missing_ids) == 1

    # Reload doc1 from DB
    result = await db_session.execute(
        select(Document).where(Document.path == str(file1_path))
    )
    doc1 = result.scalars().first()
    assert doc1.status == DocumentStatus.NOT_PRESENT


@pytest.mark.asyncio
async def test_ingest_directory_avoids_false_positives_on_filters(db_session, temp_dir):
    """Verify that filtered or limited files are NOT marked as NOT_PRESENT if they still exist."""
    # 1. First ingestion
    await ingest_directory(str(temp_dir), db_session)

    # 2. Run ingestion with a filter that excludes some existing files
    # We use a non-existent MIME filter to ensure everything is skipped by the ingestion loop
    processed_ids, missing_ids = await ingest_directory(
        str(temp_dir), db_session, mime_type_filter="application/pdf"
    )

    # 3. Verify no files were marked missing
    assert len(processed_ids) == 0
    assert len(missing_ids) == 0

    # Verify docs still have their original status in DB
    result = await db_session.execute(select(Document))
    docs = result.scalars().all()
    for doc in docs:
        assert doc.status != DocumentStatus.NOT_PRESENT


@pytest.mark.asyncio
async def test_scanner_wma_reclassification(db_session, temp_dir):
    """Verify that .wma files misidentified as video are corrected."""
    # 1. Create a .wma file and a matching DB record with INCORRECT mime_type (video/x-ms-asf)
    wma_path = temp_dir / "music.wma"
    wma_path.write_text("dummy wma content")

    doc = Document(
        path=str(wma_path),
        mime_type="video/x-ms-asf",
        file_hash="wmahash",
        file_size=wma_path.stat().st_size,
        mtime=wma_path.stat().st_mtime,
        status=DocumentStatus.COMPLETED,
    )
    db_session.add(doc)
    await db_session.commit()

    # 2. Run ingestion
    await ingest_directory(str(temp_dir), db_session)

    # 3. Verify the record is now corrected to audio
    result = await db_session.execute(select(Document).where(Document.id == doc.id))
    updated_doc = result.scalars().first()
    assert updated_doc.mime_type == "audio/x-ms-wma"


@pytest.mark.asyncio
async def test_startup_wma_reclassification(db_session, temp_dir):
    """Verify that .wma files are corrected during scanner startup."""
    from src.scanner import _load_and_queue_existing_docs

    # 1. Create a .wma file and a matching DB record with INCORRECT mime_type (video/x-ms-asf)
    wma_path = temp_dir / "music_startup.wma"
    wma_path.write_text("dummy wma content")

    doc = Document(
        path=str(wma_path),
        mime_type="video/x-ms-asf",
        file_hash="wmahash_startup",
        file_size=wma_path.stat().st_size,
        mtime=wma_path.stat().st_mtime,
        status=DocumentStatus.PENDING,
    )
    db_session.add(doc)
    await db_session.commit()

    # 2. Run startup logic
    from unittest.mock import AsyncMock, MagicMock

    mock_session_cm = AsyncMock()
    mock_session_cm.__aenter__.return_value = db_session
    mock_session_maker = MagicMock(return_value=mock_session_cm)

    await _load_and_queue_existing_docs(
        mock_session_maker, [], set(), {}, {}, asyncio.Queue()
    )

    # 3. Verify the record is now corrected to audio
    result = await db_session.execute(select(Document).where(Document.id == doc.id))
    updated_doc = result.scalars().first()
    assert updated_doc.mime_type == "audio/x-ms-wma"
