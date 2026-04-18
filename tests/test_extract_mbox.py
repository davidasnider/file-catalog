import mailbox


from src.scripts.extract_and_cleanup_mbox import (
    _normalize_subject,
    _sanitize_filename,
    _extract_addr_local,
    _extract_date_prefix,
    _build_threads,
    _is_mailbox_file,
    extract_mailbox,
    process_directory,
)


class TestNormalizeSubject:
    def test_strips_re(self):
        assert _normalize_subject("Re: Hello") == "Hello"

    def test_strips_fwd(self):
        assert _normalize_subject("Fwd: Hello") == "Hello"

    def test_strips_fw(self):
        assert _normalize_subject("FW: Hello") == "Hello"

    def test_strips_nested_prefixes(self):
        assert _normalize_subject("Re: Re: Fwd: Meeting Notes") == "Meeting Notes"

    def test_strips_numbered_re(self):
        assert _normalize_subject("Re[2]: Hello") == "Hello"

    def test_empty_subject(self):
        assert _normalize_subject("") == ""

    def test_no_prefix(self):
        assert _normalize_subject("Tax Assessment") == "Tax Assessment"

    def test_case_insensitive(self):
        assert _normalize_subject("RE: FW: Important") == "Important"


class TestSanitizeFilename:
    def test_basic(self):
        assert _sanitize_filename("hello world") == "hello_world"

    def test_special_chars(self):
        result = _sanitize_filename("foo/bar:baz<qux>")
        assert "/" not in result
        assert ":" not in result
        assert "<" not in result

    def test_empty(self):
        assert _sanitize_filename("") == "unnamed"

    def test_truncation(self):
        long_name = "a" * 200
        result = _sanitize_filename(long_name, max_len=50)
        assert len(result) <= 50


class TestExtractAddrLocal:
    def test_angle_bracket(self):
        assert _extract_addr_local("John Doe <john@example.com>") == "john"

    def test_bare_address(self):
        assert _extract_addr_local("john@example.com") == "john"

    def test_empty(self):
        assert _extract_addr_local("") == "unknown"


class TestExtractDatePrefix:
    def test_valid_date(self):
        result = _extract_date_prefix("Mon, 15 Jan 2024 10:00:00 +0000")
        assert result == "2024-01-15"

    def test_invalid_date(self):
        result = _extract_date_prefix("not a date")
        assert result == "0000-00-00"

    def test_empty(self):
        assert _extract_date_prefix("") == "0000-00-00"


class TestIsMailboxFile:
    def test_mbox_extension(self, tmp_path):
        f = tmp_path / "test.mbox"
        f.write_text("From sender@example.com\n\nBody\n")
        assert _is_mailbox_file(f) is True

    def test_mbx_extension(self, tmp_path):
        f = tmp_path / "test.mbx"
        f.write_text("From sender@example.com\n\nBody\n")
        assert _is_mailbox_file(f) is True

    def test_mbx_with_number(self, tmp_path):
        f = tmp_path / "In.mbx.002"
        f.write_text("From sender@example.com\n\nBody\n")
        assert _is_mailbox_file(f) is True

    def test_non_mailbox(self, tmp_path):
        f = tmp_path / "readme.txt"
        f.write_text("Hello")
        assert _is_mailbox_file(f) is False


def _make_msg(
    subject="Test",
    from_addr="sender@example.com",
    to_addr="recipient@example.com",
    body="Hello",
    date="Mon, 15 Jan 2024 10:00:00 +0000",
    message_id=None,
    in_reply_to=None,
    references=None,
):
    """Helper to create an email.message.Message for testing."""
    msg = mailbox.mboxMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Date"] = date
    if message_id:
        msg["Message-ID"] = f"<{message_id}>"
    if in_reply_to:
        msg["In-Reply-To"] = f"<{in_reply_to}>"
    if references:
        msg["References"] = " ".join(f"<{r}>" for r in references)
    msg.set_payload(body)
    return msg


class TestBuildThreads:
    def test_thread_by_references(self):
        msg1 = _make_msg(
            subject="Tax Question",
            message_id="msg1@example.com",
            date="Mon, 15 Jan 2024 10:00:00 +0000",
        )
        msg2 = _make_msg(
            subject="Re: Tax Question",
            message_id="msg2@example.com",
            in_reply_to="msg1@example.com",
            references=["msg1@example.com"],
            date="Tue, 16 Jan 2024 10:00:00 +0000",
        )
        msg3 = _make_msg(
            subject="Re: Re: Tax Question",
            message_id="msg3@example.com",
            in_reply_to="msg2@example.com",
            references=["msg1@example.com", "msg2@example.com"],
            date="Wed, 17 Jan 2024 10:00:00 +0000",
        )

        threads, standalone = _build_threads([msg1, msg2, msg3])

        assert len(threads) == 1
        assert len(standalone) == 0

        thread_msgs = list(threads.values())[0]
        assert len(thread_msgs) == 3

    def test_thread_by_subject_fallback(self):
        msg1 = _make_msg(
            subject="Meeting Notes",
            date="Mon, 15 Jan 2024 10:00:00 +0000",
        )
        msg2 = _make_msg(
            subject="Re: Meeting Notes",
            date="Tue, 16 Jan 2024 10:00:00 +0000",
        )

        threads, standalone = _build_threads([msg1, msg2])

        assert len(threads) == 1
        assert len(standalone) == 0

    def test_standalone_unique_subjects(self):
        msg1 = _make_msg(subject="Hello")
        msg2 = _make_msg(subject="Goodbye")

        threads, standalone = _build_threads([msg1, msg2])

        assert len(threads) == 0
        assert len(standalone) == 2

    def test_mixed_threads_and_standalone(self):
        msg1 = _make_msg(subject="Thread A", message_id="a1@x.com")
        msg2 = _make_msg(
            subject="Re: Thread A",
            message_id="a2@x.com",
            in_reply_to="a1@x.com",
        )
        msg3 = _make_msg(subject="Standalone Email")

        threads, standalone = _build_threads([msg1, msg2, msg3])

        assert len(threads) == 1
        assert len(standalone) == 1

    def test_empty_messages(self):
        threads, standalone = _build_threads([])
        assert len(threads) == 0
        assert len(standalone) == 0


class TestExtractMailbox:
    def test_basic_extraction(self, tmp_path):
        # Create a test mbox file
        mbox_path = tmp_path / "test.mbox"
        mbox = mailbox.mbox(str(mbox_path))

        msg = mailbox.mboxMessage()
        msg["Subject"] = "Hello World"
        msg["From"] = "sender@example.com"
        msg["Date"] = "Mon, 15 Jan 2024 10:00:00 +0000"
        msg.set_payload("This is the body.")
        mbox.add(msg)
        mbox.close()

        dest_dir = tmp_path / "test_extracted"
        count = extract_mailbox(mbox_path, dest_dir)

        assert count == 1
        assert dest_dir.exists()
        eml_files = list(dest_dir.glob("*.eml"))
        assert len(eml_files) == 1

    def test_thread_extraction(self, tmp_path):
        mbox_path = tmp_path / "test.mbox"
        mbox = mailbox.mbox(str(mbox_path))

        msg1 = mailbox.mboxMessage()
        msg1["Subject"] = "Tax Discussion"
        msg1["From"] = "alice@example.com"
        msg1["Date"] = "Mon, 15 Jan 2024 10:00:00 +0000"
        msg1["Message-ID"] = "<msg1@example.com>"
        msg1.set_payload("Initial question about taxes.")
        mbox.add(msg1)

        msg2 = mailbox.mboxMessage()
        msg2["Subject"] = "Re: Tax Discussion"
        msg2["From"] = "bob@example.com"
        msg2["Date"] = "Tue, 16 Jan 2024 10:00:00 +0000"
        msg2["Message-ID"] = "<msg2@example.com>"
        msg2["In-Reply-To"] = "<msg1@example.com>"
        msg2["References"] = "<msg1@example.com>"
        msg2.set_payload("Reply about taxes.")
        mbox.add(msg2)

        mbox.close()

        dest_dir = tmp_path / "test_extracted"
        count = extract_mailbox(mbox_path, dest_dir)

        assert count == 2
        # Should have a thread subdirectory
        subdirs = [d for d in dest_dir.iterdir() if d.is_dir()]
        assert len(subdirs) == 1
        assert "thread_" in subdirs[0].name
        assert "Tax_Discussion" in subdirs[0].name

        # Thread directory should contain 2 .eml files
        thread_emls = list(subdirs[0].glob("*.eml"))
        assert len(thread_emls) == 2

    def test_empty_mbox(self, tmp_path):
        mbox_path = tmp_path / "empty.mbox"
        mbox = mailbox.mbox(str(mbox_path))
        mbox.close()

        dest_dir = tmp_path / "empty_extracted"
        count = extract_mailbox(mbox_path, dest_dir)

        assert count == 0


class TestProcessDirectory:
    def test_dry_run(self, tmp_path, capsys):
        # Create a simple mbox file
        mbox_path = tmp_path / "test.mbox"
        mbox = mailbox.mbox(str(mbox_path))
        msg = mailbox.mboxMessage()
        msg["Subject"] = "Test"
        msg["From"] = "test@example.com"
        msg.set_payload("Body")
        mbox.add(msg)
        mbox.close()

        process_directory(str(tmp_path), recursive=True, dry_run=True, keep=False)

        # Original should still exist
        assert mbox_path.exists()
        # No extracted directory should exist
        extracted = tmp_path / "test_extracted"
        assert not extracted.exists()

    def test_extract_and_delete(self, tmp_path):
        mbox_path = tmp_path / "test.mbox"
        mbox = mailbox.mbox(str(mbox_path))
        msg = mailbox.mboxMessage()
        msg["Subject"] = "Test"
        msg["From"] = "test@example.com"
        msg.set_payload("Body")
        mbox.add(msg)
        mbox.close()

        process_directory(str(tmp_path), recursive=True, dry_run=False, keep=False)

        # Original should be deleted
        assert not mbox_path.exists()
        # Extracted directory should exist
        extracted = tmp_path / "test_extracted"
        assert extracted.exists()

    def test_extract_and_keep(self, tmp_path):
        mbox_path = tmp_path / "test.mbox"
        mbox = mailbox.mbox(str(mbox_path))
        msg = mailbox.mboxMessage()
        msg["Subject"] = "Test"
        msg["From"] = "test@example.com"
        msg.set_payload("Body")
        mbox.add(msg)
        mbox.close()

        process_directory(str(tmp_path), recursive=True, dry_run=False, keep=True)

        # Original should still exist
        assert mbox_path.exists()
        # Extracted directory should also exist
        extracted = tmp_path / "test_extracted"
        assert extracted.exists()

    def test_mbx_numbered_file(self, tmp_path):
        """Test that In.mbx.002 style files are discovered and extracted."""
        mbox_path = tmp_path / "In.mbx.002"
        mbox = mailbox.mbox(str(mbox_path))
        msg = mailbox.mboxMessage()
        msg["Subject"] = "Important"
        msg["From"] = "test@example.com"
        msg.set_payload("Body")
        mbox.add(msg)
        mbox.close()

        process_directory(str(tmp_path), recursive=True, dry_run=False, keep=False)

        # Original should be deleted
        assert not mbox_path.exists()
        # Extracted directory should exist (derived from "In")
        extracted_dirs = [
            d for d in tmp_path.iterdir() if d.is_dir() and "extracted" in d.name
        ]
        assert len(extracted_dirs) == 1

    def test_skips_non_mailbox(self, tmp_path):
        txt_file = tmp_path / "readme.txt"
        txt_file.write_text("Not a mailbox")

        process_directory(str(tmp_path), recursive=True, dry_run=False, keep=False)

        # File should be untouched
        assert txt_file.exists()
