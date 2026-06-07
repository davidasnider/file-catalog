import asyncio
import json

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from sqlmodel import select

from src.db.models import AnalysisTask, Document, DocumentStatus, TaskStatus
from src.scanner import _batch_check_doc_errors, compute_file_hash, ingest_directory


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

    # Should only process the original 2 .txt files, as .js, .py, .css, .ttf, .c, and .xml are in IGNORED_EXTENSIONS
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
async def test_ingest_directory_excludes_by_mime_type(db_session, temp_dir, mocker):
    """Verify that files are ignored based on detected MIME type even if extension is allowed."""
    from src.scanner import ingest_directory

    # Create a file with a generic extension that would normally be scanned
    xhtml_file = temp_dir / "page.xhtml"
    xhtml_file.write_text("<html><body>Hello</body></html>")

    # Mock detect_file_type to return application/xhtml+xml ONLY for the .xhtml file
    def mock_detect(path):
        if str(path).endswith(".xhtml"):
            return "application/xhtml+xml"
        return "text/plain"

    mocker.patch("src.scanner.detect_file_type", side_effect=mock_detect)

    # Ingest directory
    processed_ids, _ = await ingest_directory(str(temp_dir), db_session)

    # Should skip the .xhtml file because application/xhtml+xml is in IGNORED_MIME_TYPES.
    # It should still process the 2 .txt files from the temp_dir fixture.
    assert len(processed_ids) == 2

    result = await db_session.execute(
        select(Document).where(Document.path.like("%page.xhtml"))
    )
    doc = result.scalars().first()
    assert doc is None


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
                assert doc is not None, (
                    f"Document {item} was enqueued before it was committed to the DB!"
                )
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
    # NOTE: COMPLETED files that match metadata but are skipped by filter
    # are still added to processed_ids to ensure they aren't marked NOT_PRESENT.
    assert len(processed_ids) == 2
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


def test_mlx_provider_enable_thinking_toggling():
    """Verify that MLXProvider defaults enable_thinking to False, and respects enable_thinking=True when passed."""
    from src.llm.mlx_provider import MLXProvider
    from unittest.mock import MagicMock, patch

    # Mock the models and tokenizers so we don't load real files on disk
    mock_model = MagicMock()
    mock_tokenizer = MagicMock()
    mock_tokenizer.apply_chat_template = MagicMock(return_value="formatted prompt")

    with (
        patch(
            "src.llm.mlx_provider.load",
            return_value=(mock_model, mock_tokenizer),
            create=True,
        ),
        patch(
            "src.llm.mlx_provider.generate", return_value="dummy response", create=True
        ),
        patch(
            "src.llm.mlx_provider.make_sampler", return_value=MagicMock(), create=True
        ),
        patch(
            "src.llm.mlx_provider.make_logits_processors",
            return_value=MagicMock(),
            create=True,
        ),
        patch("src.llm.mlx_provider.HAS_MLX", True, create=True),
    ):
        provider = MLXProvider(model_path="dummy", is_vision=False)
        provider.use_chat_template = True

        # Test default call (without enable_thinking passed)
        import asyncio

        original_loop = None
        try:
            policy = asyncio.get_event_loop_policy()
            if (
                hasattr(policy, "_local")
                and getattr(policy._local, "_loop", None) is not None
            ):
                original_loop = policy._local._loop
        except Exception:
            pass

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            # Mock run_in_executor to execute the sync function immediately
            async def mock_run_in_executor(executor, func, *args):
                return func(*args)

            with (
                patch("asyncio.get_running_loop", return_value=loop),
                patch.object(loop, "run_in_executor", new=mock_run_in_executor),
                patch("src.llm.mlx_provider.get_mlx_gpu_lock"),
            ):
                # Default: enable_thinking should be False
                loop.run_until_complete(provider.generate("test prompt"))
                mock_tokenizer.apply_chat_template.assert_called_with(
                    [
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": "test prompt"},
                    ],
                    tokenize=False,
                    add_generation_prompt=True,
                    enable_thinking=False,
                )

                # Explicit enable_thinking=True
                loop.run_until_complete(
                    provider.generate("test prompt", enable_thinking=True)
                )
                mock_tokenizer.apply_chat_template.assert_called_with(
                    [
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": "test prompt"},
                    ],
                    tokenize=False,
                    add_generation_prompt=True,
                    enable_thinking=True,
                )
        finally:
            loop.close()
            if original_loop is not None:
                asyncio.set_event_loop(original_loop)
            else:
                asyncio.set_event_loop(None)


# ── _batch_check_doc_errors tests ──────────────────────────────────────


@pytest.fixture
def async_session_maker(test_engine):
    """Session factory for _batch_check_doc_errors tests."""
    return async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def seeded_db(db_session):
    """Seed the test DB with Documents for _batch_check_doc_errors tests."""
    docs = [
        Document(
            id=i,
            path=f"/tmp/test_{i}.txt",
            mime_type="text/plain",
            file_hash=f"hash_{i}",
            file_size=100,
            mtime=0,
            status=DocumentStatus.COMPLETED,
        )
        for i in range(1, 11)
    ]
    for doc in docs:
        db_session.add(doc)
    await db_session.commit()
    return [d.id for d in docs]


async def _create_analysis_task(db_session, doc_id, task_name, result_data):
    """Helper to create an AnalysisTask with the given result_data JSON."""
    task = AnalysisTask(
        document_id=doc_id,
        task_name=task_name,
        status=TaskStatus.COMPLETED,
        result_data=result_data,
    )
    db_session.add(task)
    await db_session.commit()


@pytest.mark.asyncio
async def test_batch_check_doc_errors_empty_ids(async_session_maker):
    """Empty processed_doc_ids should return early without queries."""
    missing_models = set()
    missing_libraries = set()
    await _batch_check_doc_errors(
        async_session_maker, set(), missing_models, missing_libraries
    )
    assert len(missing_models) == 0
    assert len(missing_libraries) == 0


@pytest.mark.asyncio
async def test_batch_check_doc_errors_model_not_found(
    async_session_maker, db_session, seeded_db
):
    """Documents with 'model not found' errors are collected."""
    await _create_analysis_task(
        db_session,
        seeded_db[0],
        "summarize",
        json.dumps({"error": "model not found: llama-3.2-3b"}),
    )
    await _create_analysis_task(
        db_session,
        seeded_db[1],
        "summarize",
        json.dumps({"error": "MODEL NOT FOUND: mistral-7b"}),
    )
    # This one should NOT match (no error key)
    await _create_analysis_task(
        db_session,
        seeded_db[2],
        "ocr",
        json.dumps({"text": "some extracted text"}),
    )

    missing_models = set()
    missing_libraries = set()
    await _batch_check_doc_errors(
        async_session_maker, set(seeded_db), missing_models, missing_libraries
    )

    assert len(missing_models) == 2
    assert any("llama-3.2-3b" in m for m in missing_models)
    assert any("mistral-7b" in m for m in missing_models)
    assert len(missing_libraries) == 0


@pytest.mark.asyncio
async def test_batch_check_doc_errors_library_not_installed(
    async_session_maker, db_session, seeded_db
):
    """Documents with 'llama-cpp-python is not installed' are collected."""
    await _create_analysis_task(
        db_session,
        seeded_db[0],
        "summarize",
        json.dumps({"error": "llama-cpp-python is not installed"}),
    )

    missing_models = set()
    missing_libraries = set()
    await _batch_check_doc_errors(
        async_session_maker, set(seeded_db), missing_models, missing_libraries
    )

    assert len(missing_models) == 0
    assert len(missing_libraries) == 1
    assert "llama-cpp-python is not installed" in next(iter(missing_libraries))


@pytest.mark.asyncio
async def test_batch_check_doc_errors_other_errors_ignored(
    async_session_maker, db_session, seeded_db
):
    """Errors unrelated to models/libraries are not collected."""
    await _create_analysis_task(
        db_session,
        seeded_db[0],
        "summarize",
        json.dumps({"error": "timeout exceeded"}),
    )
    await _create_analysis_task(
        db_session,
        seeded_db[1],
        "ocr",
        json.dumps({"error": "unsupported file format"}),
    )

    missing_models = set()
    missing_libraries = set()
    await _batch_check_doc_errors(
        async_session_maker, set(seeded_db), missing_models, missing_libraries
    )

    assert len(missing_models) == 0
    assert len(missing_libraries) == 0


@pytest.mark.asyncio
async def test_batch_check_doc_errors_null_result_data_filtered(
    async_session_maker, db_session, seeded_db
):
    """Documents with NULL result_data are filtered at SQL level."""
    await _create_analysis_task(
        db_session,
        seeded_db[0],
        "summarize",
        json.dumps({"error": "model not found: phi-3"}),
    )
    # Doc 1 has NULL result_data — should be filtered by .isnot(None) in SQL
    task_null = AnalysisTask(
        document_id=seeded_db[1],
        task_name="ocr",
        status=TaskStatus.COMPLETED,
        result_data=None,
    )
    db_session.add(task_null)
    await db_session.commit()

    missing_models = set()
    missing_libraries = set()
    await _batch_check_doc_errors(
        async_session_maker, set(seeded_db), missing_models, missing_libraries
    )

    # Only the model-not-found error should be collected
    assert len(missing_models) == 1
    assert "phi-3" in next(iter(missing_models))


@pytest.mark.asyncio
async def test_batch_check_doc_errors_no_error_substring_filtered(
    async_session_maker, db_session, seeded_db
):
    """result_data without '\"error\"' substring is filtered at SQL level."""
    await _create_analysis_task(
        db_session,
        seeded_db[0],
        "ocr",
        json.dumps({"text": "no error here"}),
    )
    await _create_analysis_task(
        db_session,
        seeded_db[1],
        "summarize",
        json.dumps({"error": "model not found: gemma-2b"}),
    )

    missing_models = set()
    missing_libraries = set()
    await _batch_check_doc_errors(
        async_session_maker, set(seeded_db), missing_models, missing_libraries
    )

    # Only the doc with 'error' substring should be scanned
    assert len(missing_models) == 1
    assert "gemma-2b" in next(iter(missing_models))
    assert len(missing_libraries) == 0


@pytest.mark.asyncio
async def test_batch_check_doc_errors_invalid_json_handled(
    async_session_maker, db_session, seeded_db
):
    """Invalid JSON in result_data is caught (JSONDecodeError) and skipped."""
    await _create_analysis_task(
        db_session,
        seeded_db[0],
        "summarize",
        '{"error": "model not found: qwen", broken json',
    )
    await _create_analysis_task(
        db_session,
        seeded_db[1],
        "summarize",
        json.dumps({"error": "model not found: phi-3"}),
    )

    missing_models = set()
    missing_libraries = set()
    await _batch_check_doc_errors(
        async_session_maker, set(seeded_db), missing_models, missing_libraries
    )

    # Invalid JSON is ignored; valid error is collected
    assert len(missing_models) == 1
    assert "phi-3" in next(iter(missing_models))


@pytest.mark.asyncio
async def test_batch_check_doc_errors_typeerror_handled(
    async_session_maker, db_session, seeded_db
):
    """Non-dict JSON (e.g. a list) is silently skipped via isinstance check."""
    await _create_analysis_task(
        db_session,
        seeded_db[0],
        "summarize",
        json.dumps([1, 2, 3]),  # List, not dict — silently skipped via isinstance check
    )
    await _create_analysis_task(
        db_session,
        seeded_db[1],
        "summarize",
        json.dumps({"error": "model not found: phi-3"}),
    )

    missing_models = set()
    missing_libraries = set()
    await _batch_check_doc_errors(
        async_session_maker, set(seeded_db), missing_models, missing_libraries
    )

    # List result_data is skipped; valid error is collected
    assert len(missing_models) == 1
    assert "phi-3" in next(iter(missing_models))


@pytest.mark.asyncio
async def test_batch_check_doc_errors_chunking(
    async_session_maker, db_session, test_engine
):
    """Documents beyond the 900-chunk boundary are still checked."""
    # Create 950 documents, each with an AnalysisTask

    docs = [
        Document(
            id=i,
            path=f"/tmp/chunk_{i}.txt",
            mime_type="text/plain",
            file_hash=f"chunk_hash_{i}",
            file_size=100,
            mtime=0,
            status=DocumentStatus.COMPLETED,
        )
        for i in range(1, 951)
    ]
    for doc in docs:
        db_session.add(doc)
    await db_session.commit()

    # Add error to doc #1 (first chunk) and doc #950 (second chunk)
    await _create_analysis_task(
        db_session,
        1,
        "summarize",
        json.dumps({"error": "model not found: first-chunk-model"}),
    )
    await _create_analysis_task(
        db_session,
        950,
        "summarize",
        json.dumps({"error": "llama-cpp-python is not installed"}),
    )

    doc_ids = set(range(1, 951))
    missing_models = set()
    missing_libraries = set()
    await _batch_check_doc_errors(
        async_session_maker, doc_ids, missing_models, missing_libraries
    )

    assert len(missing_models) == 1
    assert "first-chunk-model" in next(iter(missing_models))
    assert len(missing_libraries) == 1


@pytest.mark.asyncio
async def test_batch_check_doc_errors_mixed_scenario(
    async_session_maker, db_session, seeded_db
):
    """Mixed scenario: model errors, library errors, NULLs, and valid data."""
    # Model error
    await _create_analysis_task(
        db_session,
        seeded_db[0],
        "summarize",
        json.dumps({"error": "model not found: tinyllama"}),
    )
    # Library error
    await _create_analysis_task(
        db_session,
        seeded_db[1],
        "estate",
        json.dumps({"error": "llama-cpp-python is not installed"}),
    )
    # NULL result_data
    task_null = AnalysisTask(
        document_id=seeded_db[2],
        task_name="ocr",
        status=TaskStatus.COMPLETED,
        result_data=None,
    )
    db_session.add(task_null)
    # Valid result — no error substring
    await _create_analysis_task(
        db_session,
        seeded_db[3],
        "ocr",
        json.dumps({"text": "extracted ok"}),
    )
    # Unrelated error
    await _create_analysis_task(
        db_session,
        seeded_db[4],
        "pii",
        json.dumps({"error": "permission denied"}),
    )
    await db_session.commit()

    missing_models = set()
    missing_libraries = set()
    await _batch_check_doc_errors(
        async_session_maker, set(seeded_db), missing_models, missing_libraries
    )

    assert len(missing_models) == 1
    assert "tinyllama" in next(iter(missing_models))
    assert len(missing_libraries) == 1
    assert "llama-cpp-python is not installed" in next(iter(missing_libraries))
