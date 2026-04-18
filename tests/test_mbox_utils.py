import os
import tempfile
from src.core.mbox_utils import RobustMbox


def create_mbox_file(messages: list[bytes]) -> str:
    """Helper to create a temporary mbox file with raw bytes."""
    fd, path = tempfile.mkstemp(suffix=".mbox")
    with os.fdopen(fd, "wb") as f:
        for msg in messages:
            f.write(msg)
    return path


def test_robust_mbox_standard_ascii():
    """Test RobustMbox with standard ASCII messages."""
    msg1 = (
        b"From sender@example.com Mon Jan 1 00:00:00 2024\nSubject: Test 1\n\nBody 1\n"
    )
    msg2 = (
        b"From sender@example.com Mon Jan 1 00:00:01 2024\nSubject: Test 2\n\nBody 2\n"
    )
    path = create_mbox_file([msg1, msg2])

    try:
        mbox = RobustMbox(path)
        messages = list(mbox)
        assert len(messages) == 2
        assert messages[0].get_from() == "sender@example.com Mon Jan 1 00:00:00 2024"
        assert messages[0]["Subject"] == "Test 1"
        assert messages[1].get_from() == "sender@example.com Mon Jan 1 00:00:01 2024"
        assert messages[1]["Subject"] == "Test 2"
        mbox.close()
    finally:
        os.remove(path)


def test_robust_mbox_non_ascii_from_line():
    """Test RobustMbox with non-ASCII characters in the From line (Latin-1/legacy)."""
    # Simulate a From line with a special character (e.g., from old Mac or European systems)
    # \xeb is 'ë' in Latin-1
    from_line = b"From user\xeb@example.com Mon Jan 1 00:00:00 2024\n"
    msg = from_line + b"Subject: Encoding Test\n\nBody\n"
    path = create_mbox_file([msg])

    try:
        mbox = RobustMbox(path)
        messages = list(mbox)
        assert len(messages) == 1
        # Should have decoded using latin-1 fallback
        from_val = messages[0].get_from()
        assert from_val == "userë@example.com Mon Jan 1 00:00:00 2024"
        mbox.close()
    finally:
        os.remove(path)


def test_robust_mbox_mixed_line_endings():
    """Test RobustMbox with CRLF line endings in From lines."""
    # Standard library mbox.py/mailbox.py often has trouble with CRLF From lines
    msg1 = b"From a@b.com Mon Jan 1 00:00:00 2024\r\nSubject: CRLF\r\n\r\nBody\r\n"
    msg2 = b"From c@d.com Mon Jan 1 00:00:01 2024\nSubject: LF\n\nBody\n"
    path = create_mbox_file([msg1, msg2])

    try:
        mbox = RobustMbox(path)
        messages = list(mbox)
        assert len(messages) == 2
        assert messages[0].get_from() == "a@b.com Mon Jan 1 00:00:00 2024"
        assert messages[1].get_from() == "c@d.com Mon Jan 1 00:00:01 2024"
        mbox.close()
    finally:
        os.remove(path)
