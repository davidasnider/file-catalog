import asyncio
from unittest.mock import patch, MagicMock
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
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


class TestFetchAllTasksForDocuments:
    """Tests for fetch_all_tasks_for_documents using a real in-memory SQLite database.

    Uses an actual SQLite backend so the json_each() query construction,
    task grouping, and _is_sqlite_backend detection are all exercised.
    """

    @staticmethod
    def _make_task(document_id, task_name="TextExtractor"):
        """Helper to create a mock AnalysisTask."""
        task = MagicMock()
        task.document_id = document_id
        task.task_name = task_name
        return task

    @staticmethod
    def _setup_db(session):
        """Create tables and seed tasks in the test database."""
        from app import AnalysisTask

        session.execute(AnalysisTask.__table__.create(checkfirst=True))

        tasks = [
            AnalysisTask(document_id=1, task_name="TextExtractor"),
            AnalysisTask(document_id=1, task_name="Summarizer"),
            AnalysisTask(document_id=2, task_name="TextExtractor"),
        ]
        session.add_all(tasks)
        session.commit()

    @patch("app.async_session_maker")
    def test_fetch_all_tasks_returns_correct_grouping(self, mock_session_maker):
        """Verify tasks are correctly grouped by document_id via real SQL."""
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        mock_session_maker.return_value = async_session()

        # Set up the database in a separate event loop (asyncio.run is used by the function)
        async def _setup():
            async with async_session() as s:
                self._setup_db(s)

        asyncio.run(_setup())

        from app import fetch_all_tasks_for_documents, _is_sqlite_backend

        _is_sqlite_backend.cache_clear()
        fetch_all_tasks_for_documents.cache_clear()

        result = fetch_all_tasks_for_documents([1, 2])

        assert len(result[1]) == 2
        assert len(result[2]) == 1

    def test_fetch_all_tasks_empty_doc_ids(self):
        """Empty doc_ids should return an empty dict without hitting the DB."""
        from app import fetch_all_tasks_for_documents

        fetch_all_tasks_for_documents.cache_clear()
        result = fetch_all_tasks_for_documents([])

        assert result == {}

    @patch("app.async_session_maker")
    def test_fetch_all_tasks_missing_doc_ids_get_empty_lists(self, mock_session_maker):
        """Document IDs with no matching tasks should get empty lists."""
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        mock_session_maker.return_value = async_session()

        async def _setup():
            async with async_session() as s:
                self._setup_db(s)

        asyncio.run(_setup())

        from app import fetch_all_tasks_for_documents, _is_sqlite_backend

        _is_sqlite_backend.cache_clear()
        fetch_all_tasks_for_documents.cache_clear()

        result = fetch_all_tasks_for_documents([1, 2, 3])

        assert len(result[1]) == 1
        assert result[2] == []
        assert result[3] == []

    @patch("app.async_session_maker")
    def test_fetch_all_tasks_single_document(self, mock_session_maker):
        """Single document ID should work correctly."""
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        mock_session_maker.return_value = async_session()

        async def _setup():
            async with async_session() as s:
                self._setup_db(s)

        asyncio.run(_setup())

        from app import fetch_all_tasks_for_documents, _is_sqlite_backend

        _is_sqlite_backend.cache_clear()
        fetch_all_tasks_for_documents.cache_clear()

        result = fetch_all_tasks_for_documents([1])

        assert len(result[1]) == 2
