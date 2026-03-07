import pytest
import os

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
    processed_ids = await ingest_directory(str(temp_dir), db_session)
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
    processed_ids = await ingest_directory(str(temp_dir), db_session)
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
    processed_ids = await ingest_directory(str(temp_dir), db_session)
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

    # Ingest directory
    processed_ids = await ingest_directory(str(temp_dir), db_session)

    # Should only process the original 2 .txt files, as .js, .py, and .css are in IGNORED_EXTENSIONS
    assert len(processed_ids) == 2

    result = await db_session.execute(select(Document))
    docs = result.scalars().all()
    assert len(docs) == 2

    for doc in docs:
        _, ext = os.path.splitext(doc.path)
        assert ext == ".txt"
