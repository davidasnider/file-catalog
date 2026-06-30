from unittest.mock import patch
from contextlib import asynccontextmanager
from src.db.models import AnalysisTask, Document
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlmodel import SQLModel
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


def _build_test_db(task_configs):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    async def init():
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

        async_session = sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        async with async_session() as session:
            for doc_id, task_name in task_configs:
                # Add doc if it doesn't exist
                doc = await session.get(Document, doc_id)
                if not doc:
                    doc = Document(id=doc_id, path=f"/tmp/{doc_id}")
                    session.add(doc)
                task = AnalysisTask(document_id=doc_id, task_name=task_name)
                session.add(task)
            await session.commit()

    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop - safe to use asyncio.run()
        asyncio.run(init())
    else:
        # Already in an event loop (e.g., pytest-asyncio)
        loop.run_until_complete(init())

    return engine


class TestFetchAllTasksForDocuments:
    """Tests for fetch_all_tasks_for_documents using SQLite json_each()."""

    @patch("app.async_session_maker")
    def test_fetch_all_tasks_returns_correct_grouping(self, mock_session_maker):
        """Verify tasks are correctly grouped by document_id via real SQL."""
        engine = _build_test_db(
            [
                (1, "TextExtractor"),
                (1, "Summarizer"),
                (2, "TextExtractor"),
            ]
        )
        real_sm = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        @asynccontextmanager
        async def mock_sm():
            async with real_sm() as session:
                yield session

        mock_session_maker.side_effect = mock_sm
        doc_ids = [1, 2]

        from app import fetch_all_tasks_for_documents

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

    @patch("app.async_session_maker")
    def test_fetch_all_tasks_missing_doc_ids_get_empty_lists(self, mock_session_maker):
        """Document IDs with no matching tasks should get empty lists."""
        engine = _build_test_db(
            [
                (1, "TextExtractor"),
            ]
        )
        real_sm = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        @asynccontextmanager
        async def mock_sm():
            async with real_sm() as session:
                yield session

        mock_session_maker.side_effect = mock_sm
        doc_ids = [1, 2, 3]

        from app import fetch_all_tasks_for_documents

        fetch_all_tasks_for_documents.clear()
        result = fetch_all_tasks_for_documents(doc_ids)

        assert len(result[1]) == 1
        assert result[2] == []
        assert result[3] == []

    @patch("app.async_session_maker")
    def test_fetch_all_tasks_single_document(self, mock_session_maker):
        """Single document ID should work correctly."""
        engine = _build_test_db(
            [
                (42, "TextExtractor"),
                (42, "Summarizer"),
            ]
        )
        real_sm = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        @asynccontextmanager
        async def mock_sm():
            async with real_sm() as session:
                yield session

        mock_session_maker.side_effect = mock_sm
        doc_ids = [42]

        from app import fetch_all_tasks_for_documents

        fetch_all_tasks_for_documents.clear()
        result = fetch_all_tasks_for_documents(doc_ids)

        assert len(result[42]) == 2

    @patch("app.async_session_maker")
    def test_fetch_all_tasks_non_sqlite_fallback(self, mock_session_maker):
        """Non-SQLite dialect should fall back to chunked IN() queries."""
        engine = _build_test_db(
            [
                (1, "TextExtractor"),
                (2, "Summarizer"),
            ]
        )
        real_sm = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        @asynccontextmanager
        async def mock_sm():
            async with real_sm() as session:
                # Mock the dialect to simulate a non-SQLite backend
                with patch.object(
                    session.bind.dialect, "name", "postgresql"
                ):
                    yield session

        mock_session_maker.side_effect = mock_sm
        doc_ids = [1, 2]

        from app import fetch_all_tasks_for_documents

        fetch_all_tasks_for_documents.clear()
        result = fetch_all_tasks_for_documents(doc_ids)

        assert len(result[1]) == 1
        assert result[1][0].task_name == "TextExtractor"
        assert len(result[2]) == 1
        assert result[2][0].task_name == "Summarizer"
