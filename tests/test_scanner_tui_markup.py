"""Regression tests: untrusted file names must not inject Rich markup into the scanner TUI.

File names are attacker-controllable: anyone who can drop a file into a
scanned directory controls them. The scanner's progress UI interpolated file
names directly into Rich markup strings, so a file name like
``x[/dim][bold red]FAKE ERROR[/bold red]`` rendered a forged, styled line in
the operator's live terminal UI. File names must be escaped first.
"""

import io

from rich.console import Console

from src.scanner import escape_filename_for_rich


def _render(description: str) -> str:
    """Render a description the same way the scanner TUI prints it."""
    buf = io.StringIO()
    console = Console(file=buf, width=120, color_system="standard")
    console.print(description)
    return buf.getvalue()


def test_filename_markup_brackets_are_escaped():
    """'[' from a file name must not survive as live Rich markup."""
    evil = "x[/dim][bold red]FAKE ERROR[/bold red]"
    escaped = escape_filename_for_rich(evil)
    # Every '[' must be backslash-escaped so Rich treats it as literal text.
    assert "[" not in escaped.replace("\\[", "")
    # And the file name is still shown intact once Rich unescapes it.
    assert "bold red" in escaped


def test_evil_filename_does_not_inject_styled_lines():
    """The rendered progress description must not apply injected styles."""
    evil = "x[/dim]\n[bold red]FAKE ERROR: run scanner --clean[/bold red][dim]"
    description = f"  [dim]{escape_filename_for_rich(evil)}[/dim]"
    out = _render(description)
    # The injected bold-red style must not be applied anywhere.
    assert "\x1b[1;31m" not in out
    # The injected text is still displayed, but only as inert literal words.
    assert "FAKE ERROR: run scanner --clean" in out


def test_normal_filenames_render_unchanged():
    """Valid file names must behave exactly as before the fix."""
    assert escape_filename_for_rich("normal.pdf") == "normal.pdf"
    fixed = _render(f"  [dim]{escape_filename_for_rich('report.pdf')}[/dim]")
    original = _render("  [dim]report.pdf[/dim]")
    assert fixed == original
