import email
import email.policy
import logging
import mailbox
from typing import Dict, Any

from src.core.plugin_registry import AnalyzerBase, register_analyzer

logger = logging.getLogger(__name__)

EMAIL_MIMES = {"message/rfc822", "application/mbox"}
EMAIL_EXTENSIONS = {".eml", ".mbox"}

MAX_EMAILS_FROM_MBOX = 100


@register_analyzer(name="EmailParser", depends_on=[], version="1.0")
class EmailParserPlugin(AnalyzerBase):
    """
    Parses .eml and .mbox files to extract sender, recipients,
    subject, body, and attachment metadata.
    """

    def should_run(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> bool:
        if mime_type in EMAIL_MIMES:
            return True
        return any(file_path.lower().endswith(ext) for ext in EMAIL_EXTENSIONS)

    async def analyze(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info(f"Parsing email file {file_path}")

        try:
            lower_path = file_path.lower()

            if lower_path.endswith(".mbox"):
                emails = self._parse_mbox(file_path)
            else:
                emails = [self._parse_eml(file_path)]

            return {
                "emails": emails,
                "total_emails": len(emails),
                "source": "email_parser",
            }

        except Exception as e:
            logger.error(f"Failed to parse email file {file_path}: {e}")
            raise Exception(f"Email parsing failed: {str(e)}")

    def _parse_eml(self, file_path: str) -> Dict[str, Any]:
        """Parse a single .eml file."""
        with open(file_path, "rb") as f:
            msg = email.message_from_binary_file(f, policy=email.policy.default)
        return self._extract_email_data(msg)

    def _parse_mbox(self, file_path: str) -> list[Dict[str, Any]]:
        """Parse an .mbox file and return a list of email dicts."""
        mbox = mailbox.mbox(file_path)
        emails = []
        for i, msg in enumerate(mbox):
            if i >= MAX_EMAILS_FROM_MBOX:
                logger.info(
                    f"Reached max email limit ({MAX_EMAILS_FROM_MBOX}) for {file_path}"
                )
                break
            emails.append(self._extract_email_data(msg))
        return emails

    def _extract_email_data(self, msg: email.message.Message) -> Dict[str, Any]:
        """Extract structured data from an email.message.Message object."""
        # Extract body text
        body_text = ""
        attachments = []

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                disposition = str(part.get("Content-Disposition", ""))

                if "attachment" in disposition:
                    attachments.append(
                        {
                            "filename": part.get_filename() or "unnamed",
                            "content_type": content_type,
                            "size": len(part.get_payload(decode=True) or b""),
                        }
                    )
                elif content_type == "text/plain" and not body_text:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        body_text = payload.decode(charset, errors="replace")
                elif content_type == "text/html" and not body_text:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        body_text = payload.decode(charset, errors="replace")
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                body_text = payload.decode(charset, errors="replace")

        return {
            "from": str(msg.get("From", "")),
            "to": str(msg.get("To", "")),
            "cc": str(msg.get("Cc", "")),
            "subject": str(msg.get("Subject", "")),
            "date": str(msg.get("Date", "")),
            "body_text": body_text.strip(),
            "attachments": attachments,
        }
