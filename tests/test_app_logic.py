from app import render_snippet
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
    # [HL_END] contains [, ], _ which are Markdown special chars
    expected = r"Hello world\[HL\_END\]"
    assert render_snippet(text) == expected


def test_render_snippet_unmatched_start_marker():
    """Unmatched start marker (truncated snippet) gets closed at end."""
    text = f"Find this: {FTS_HL_START}important term"
    expected = r"Find this: **important term**"
    assert render_snippet(text) == expected


def test_render_snippet_nested_start_marker():
    """Nested start marker inside a highlight is escaped as literal text."""
    text = f"Text {FTS_HL_START}inner {FTS_HL_START}still{FTS_HL_END} here"
    expected = r"Text **inner \[HL\_START\]still** here"
    assert render_snippet(text) == expected


def test_render_snippet_missing_start_then_end():
    """End marker before any start is escaped, then normal pair works."""
    text = f"Before{FTS_HL_END} mid {FTS_HL_START}found{FTS_HL_END} after"
    expected = r"Before\[HL\_END\] mid **found** after"
    assert render_snippet(text) == expected
