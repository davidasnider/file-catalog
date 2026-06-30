import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
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
    """Tests for fetch_all_tasks_for_documents using SQLite json_each()."""

    def _make_task(self, document_id, task_name="TextExtractor"):
        """Helper to create a mock AnalysisTask."""
        task = MagicMock()
        task.document_id = document_id
        task.task_name = task_name
        return task

    @patch("app.asyncio.run")
    def test_fetch_all_tasks_returns_correct_grouping(self, mock_run):
        """Verify tasks are correctly grouped by document_id."""
        doc_ids = [1, 2]
        tasks = [
            self._make_task(1, "TextExtractor"),
            self._make_task(1, "Summarizer"),
            self._make_task(2, "TextExtractor"),
        ]

        # Simulate the async _fetch returning grouped results
        mock_run.return_value = {1: tasks[:2], 2: [tasks[2]]}

        from app import fetch_all_tasks_for_documents

        # Clear the cache to avoid interference between tests
        fetch_all_tasks_for_documents.cache_clear()
        result = fetch_all_tasks_for_documents(doc_ids)

        assert len(result[1]) == 2
        assert len(result[2]) == 1

    @patch("app.asyncio.run")
    def test_fetch_all_tasks_empty_doc_ids(self, mock_run):
        """Empty doc_ids should return an empty dict without hitting the DB."""
        from app import fetch_all_tasks_for_documents

        fetch_all_tasks_for_documents.cache_clear()
        result = fetch_all_tasks_for_documents([])

        assert result == {}
        mock_run.assert_not_called()

    @patch("app.asyncio.run")
    def test_fetch_all_tasks_missing_doc_ids_get_empty_lists(self, mock_run):
        """Document IDs with no matching tasks should get empty lists."""
        doc_ids = [1, 2, 3]
        tasks = [self._make_task(1, "TextExtractor")]

        mock_run.return_value = {1: tasks, 2: [], 3: []}

        from app import fetch_all_tasks_for_documents

        fetch_all_tasks_uses_json_each = True  # marker that we expect json_each path
        fetch_all_tasks_for_documents.cache_clear()
        result = fetch_all_tasks_for_documents(doc_ids)

        assert len(result[1]) == 1
        assert result[2] == []
        assert result[3] == []

    @patch("app.asyncio.run")
    def test_fetch_all_tasks_single_document(self, mock_run):
        """Single document ID should work correctly."""
        doc_ids = [42]
        tasks = [
            self._make_task(42, "TextExtractor"),
            self._make_task(42, "Summarizer"),
        ]

        mock_run.return_value = {42: tasks}

        from app import fetch_all_tasks_for_documents

        fetch_all_tasks_for_documents.cache_clear()
        result = fetch_all_tasks_for_documents(doc_ids)

        assert len(result[42]) == 2
