from unittest.mock import patch, MagicMock, AsyncMock, PropertyMock
from contextlib import asynccontextmanager

import asyncio as aio

from src.ui.snippets import render_snippet
from src.db.fts import FTS_HL_START, FTS_HL_END


def test_render_snippet_basic():
    text = f"Hello {FTS_HL_START}world{FTS_HL_END}!"
    assert render_snippet(text) == r"Hello **world**\!"


def test_render_snippet_html_escaping():
    text = f"<script>alert(1)</script> {FTS_HL_START}highlight{FTS_HL_END}"
    # html.escape with quote=False turns < to &lt; and > to &gt;
    assert (
        render_snippet(text) == r"&lt;script&gt;alert\(1\)&lt;/script&gt; **highlight**"
    )


def test_render_snippet_markdown_escaping():
    text = f"Link [example](http://example.com) *bold* _italic_ {FTS_HL_START}term{FTS_HL_END}"
    # [ ] ( ) * _ . should be escaped
    expected = r"Link \[example\]\(http://example\.com\) \*bold\* \_italic\_ **term**"
    assert render_snippet(text) == expected


def test_render_snippet_quote_regression():
    # Test the regression mentioned by the reviewer
    text = f"It's a {FTS_HL_START}test{FTS_HL_END}"
    # With quote=False, ' should stay as '
    # If quote=True, ' becomes &#x27;
    # Then # is escaped to \#
    # So it becomes &\#x27;
    assert render_snippet(text) == "It's a **test**"


def test_render_snippet_double_quote():
    text = f'He said "hello" {FTS_HL_START}now{FTS_HL_END}'
    assert render_snippet(text) == 'He said "hello" **now**'


def test_render_snippet_unmatched_end_marker():
    """Unmatched end marker outside highlight gets escaped as literal text."""
    text = f"Hello world{FTS_HL_END}"
    # Control chars \x01/\x02 contain no Markdown special chars,
    # so they pass through the escaping regex unchanged.
    expected = f"Hello world{FTS_HL_END}"
    assert render_snippet(text) == expected


def test_render_snippet_unmatched_start_marker():
    """Unmatched start marker (truncated snippet) gets closed at end."""
    text = f"Find this: {FTS_HL_START}important term"
    expected = r"Find this: **important term**"
    assert render_snippet(text) == expected


def test_render_snippet_nested_start_marker():
    """Nested start marker inside a highlight is escaped as literal text."""
    text = f"Text {FTS_HL_START}inner {FTS_HL_START}still{FTS_HL_END} here"
    expected = f"Text **inner {FTS_HL_START}still** here"
    assert render_snippet(text) == expected


def test_render_snippet_missing_start_then_end():
    """End marker before any start is escaped, then normal pair works."""
    text = f"Before{FTS_HL_END} mid {FTS_HL_START}found{FTS_HL_END} after"
    expected = f"Before{FTS_HL_END} mid **found** after"
    assert render_snippet(text) == expected


def _build_test_db(seed_tasks):
    """Create an in-memory SQLite engine, build schema, and seed tasks.

    Args:
        seed_tasks: list of (document_id, task_name) tuples to insert.

    Returns:
        The configured engine (caller builds sessionmaker from it).
    """
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlmodel import SQLModel
    from src.db.models import AnalysisTask, Document

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        sm = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with sm() as session:
            # Create documents for each unique doc_id
            doc_ids = sorted(set(did for did, _ in seed_tasks))
            docs = [
                Document(id=did, path=f"/tmp/doc{did}.pdf", mime_type="application/pdf")
                for did in doc_ids
            ]
            session.add_all(docs)
            await session.flush()

            # Create tasks
            tasks = [
                AnalysisTask(document_id=did, task_name=tname)
                for did, tname in seed_tasks
            ]
            session.add_all(tasks)
            await session.commit()

    aio.run(_setup())
    return engine


class TestFetchAllTasksForDocuments:
    """Tests for fetch_all_tasks_for_documents using real in-memory SQLite."""

    def test_fetch_all_tasks_returns_correct_grouping(self):
        """Verify tasks are correctly grouped by document_id using real SQLite json_each()."""
        from sqlalchemy.ext.asyncio import AsyncSession
        from sqlalchemy.orm import sessionmaker

        engine = _build_test_db([
            (1, "TextExtractor"),
            (1, "Summarizer"),
            (2, "TextExtractor"),
        ])
        real_sm = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        @asynccontextmanager
        async def _session_ctx():
            async with real_sm() as session:
                yield session

        with patch("app.async_session_maker", return_value=_session_ctx()):
            from app import fetch_all_tasks_for_documents

            doc_ids = [1, 2]
            fetch_all_tasks_for_documents.clear()
            result = fetch_all_tasks_for_documents(doc_ids)

            assert len(result[1]) == 2
            assert len(result[2]) == 1

    def test_fetch_all_tasks_empty_doc_ids(self):
        """Empty doc_ids should return an empty dict without hitting the DB."""
        from app import fetch_all_tasks_for_documents

        fetch_all_tasks_for_documents.clear()
        result = fetch_all_tasks_for_documents([])

        assert result == {}

    def test_fetch_all_tasks_missing_doc_ids_get_empty_lists(self):
        """Document IDs with no matching tasks should get empty lists."""
        from sqlalchemy.ext.asyncio import AsyncSession
        from sqlalchemy.orm import sessionmaker

        engine = _build_test_db([(1, "TextExtractor")])
        real_sm = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        @asynccontextmanager
        async def _session_ctx():
            async with real_sm() as session:
                yield session

        with patch("app.async_session_maker", return_value=_session_ctx()):
            from app import fetch_all_tasks_for_documents

            doc_ids = [1, 2, 3]
            fetch_all_tasks_for_documents.clear()
            result = fetch_all_tasks_for_documents(doc_ids)

            assert len(result[1]) == 1
            assert result[2] == []
            assert result[3] == []

    def test_fetch_all_tasks_single_document(self):
        """Single document ID should work correctly."""
        from sqlalchemy.ext.asyncio import AsyncSession
        from sqlalchemy.orm import sessionmaker

        engine = _build_test_db([
            (42, "TextExtractor"),
            (42, "Summarizer"),
        ])
        real_sm = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        @asynccontextmanager
        async def _session_ctx():
            async with real_sm() as session:
                yield session

        with patch("app.async_session_maker", return_value=_session_ctx()):
            from app import fetch_all_tasks_for_documents

            doc_ids = [42]
            fetch_all_tasks_for_documents.clear()
            result = fetch_all_tasks_for_documents(doc_ids)

            assert len(result[42]) == 2

    def test_fetch_all_tasks_non_sqlite_fallback(self):
        """Non-SQLite backends should use the chunked IN() fallback path."""
        from sqlalchemy.ext.asyncio import AsyncSession
        from sqlalchemy.orm import sessionmaker

        engine = _build_test_db([(10, "TextExtractor")])
        real_sm = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        @asynccontextmanager
        async def _patched_session_ctx():
            """Yield a session whose bind.dialect.name is spoofed as 'postgresql'."""
            async with real_sm() as session:
                # Patch the dialect name in-place on the underlying sync engine dialect
                real_dialect = session.bind.sync_engine.dialect
                real_name = real_dialect.name
                real_dialect.name = "postgresql"
                try:
                    yield session
                finally:
                    real_dialect.name = real_name

        with patch("app.async_session_maker", return_value=_patched_session_ctx()):
            from app import fetch_all_tasks_for_documents

            doc_ids = [10]
            fetch_all_tasks_for_documents.clear()
            result = fetch_all_tasks_for_documents(doc_ids)

            # The fallback chunked IN() path should still find the task
            assert len(result[10]) == 1
