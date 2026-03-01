import pytest
from src.plugins.email_parser import EmailParserPlugin


SAMPLE_EML = b"""\
From: sender@example.com
To: recipient@example.com
Cc: cc@example.com
Subject: Test Email
Date: Mon, 01 Jan 2024 12:00:00 +0000
Content-Type: text/plain; charset="utf-8"

This is the body of the test email.
It has multiple lines.
"""

SAMPLE_MULTIPART_EML = b"""\
From: sender@example.com
To: recipient@example.com
Subject: Multipart Email
Date: Mon, 01 Jan 2024 12:00:00 +0000
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="boundary123"

--boundary123
Content-Type: text/plain; charset="utf-8"

This is the plain text body.

--boundary123
Content-Type: application/pdf
Content-Disposition: attachment; filename="report.pdf"
Content-Transfer-Encoding: base64

SGVsbG8gV29ybGQ=

--boundary123--
"""


@pytest.mark.asyncio
async def test_email_parser_eml(tmp_path):
    plugin = EmailParserPlugin()

    eml_file = tmp_path / "test.eml"
    eml_file.write_bytes(SAMPLE_EML)

    result = await plugin.analyze(str(eml_file), "message/rfc822", {})

    assert result["source"] == "email_parser"
    assert result["total_emails"] == 1

    email_data = result["emails"][0]
    assert email_data["from"] == "sender@example.com"
    assert email_data["to"] == "recipient@example.com"
    assert email_data["cc"] == "cc@example.com"
    assert email_data["subject"] == "Test Email"
    assert "body of the test email" in email_data["body_text"]
    assert email_data["attachments"] == []


@pytest.mark.asyncio
async def test_email_parser_multipart_with_attachment(tmp_path):
    plugin = EmailParserPlugin()

    eml_file = tmp_path / "multipart.eml"
    eml_file.write_bytes(SAMPLE_MULTIPART_EML)

    result = await plugin.analyze(str(eml_file), "message/rfc822", {})

    email_data = result["emails"][0]
    assert email_data["subject"] == "Multipart Email"
    assert "plain text body" in email_data["body_text"]
    assert len(email_data["attachments"]) == 1
    assert email_data["attachments"][0]["filename"] == "report.pdf"
    assert email_data["attachments"][0]["content_type"] == "application/pdf"


@pytest.mark.asyncio
async def test_email_parser_mbox(tmp_path):
    plugin = EmailParserPlugin()

    # Build a minimal mbox file with two messages
    mbox_content = (
        b"From sender@example.com Mon Jan 01 12:00:00 2024\n"
        b"From: sender@example.com\n"
        b"To: recipient@example.com\n"
        b"Subject: First Message\n"
        b"\n"
        b"Body of first message.\n"
        b"\n"
        b"From other@example.com Mon Jan 02 12:00:00 2024\n"
        b"From: other@example.com\n"
        b"To: recipient@example.com\n"
        b"Subject: Second Message\n"
        b"\n"
        b"Body of second message.\n"
    )

    mbox_file = tmp_path / "test.mbox"
    mbox_file.write_bytes(mbox_content)

    result = await plugin.analyze(str(mbox_file), "application/mbox", {})

    assert result["total_emails"] == 2
    assert result["emails"][0]["subject"] == "First Message"
    assert result["emails"][1]["subject"] == "Second Message"


@pytest.mark.asyncio
async def test_email_parser_should_run():
    plugin = EmailParserPlugin()

    assert plugin.should_run("/email.eml", "message/rfc822", {})
    assert plugin.should_run("/archive.mbox", "application/mbox", {})
    assert plugin.should_run("/email.eml", "application/octet-stream", {})

    # Should not run on non-email types
    assert not plugin.should_run("/doc.pdf", "application/pdf", {})
    assert not plugin.should_run("/image.jpg", "image/jpeg", {})
