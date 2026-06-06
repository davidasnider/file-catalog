"""Snippet rendering helpers — side-effect-free, safe to import in tests."""

import html
import re

from src.db.fts import FTS_HL_START, FTS_HL_END


def render_snippet(snippet_text: str):
    """
    Escapes HTML and Markdown in a snippet while preserving bolding for highlights.

    Processes FTS highlight markers statefully so that unmatched, nested, or
    out-of-sequence markers are treated as literal text instead of producing
    unbalanced ``**`` that would corrupt surrounding Markdown rendering.
    """
    if not snippet_text:
        return ""

    # 1. Escape HTML (using quote=False to avoid UI regression with &#x27;)
    escaped = html.escape(snippet_text, quote=False)

    # 2. Split by highlight markers to avoid escaping our own bolding
    parts = re.split(f"({re.escape(FTS_HL_START)}|{re.escape(FTS_HL_END)})", escaped)

    result = []
    in_highlight = False
    for part in parts:
        if part == FTS_HL_START:
            if not in_highlight:
                result.append("**")
                in_highlight = True
            else:
                # Nested start marker — treat as literal text
                escaped_part = re.sub(r"([\\`*_{}\[\]()#+\-.!])", r"\\\1", part)
                result.append(escaped_part)
        elif part == FTS_HL_END:
            if in_highlight:
                result.append("**")
                in_highlight = False
            else:
                # Unmatched end marker — treat as literal text
                escaped_part = re.sub(r"([\\`*_{}\[\]()#+\-.!])", r"\\\1", part)
                result.append(escaped_part)
        else:
            # Escape Markdown special characters in the content part
            escaped_part = re.sub(r"([\\`*_{}\[\]()#+\-.!])", r"\\\1", part)
            result.append(escaped_part)

    # Close any unclosed highlight (truncated snippet)
    if in_highlight:
        result.append("**")

    return "".join(result)
