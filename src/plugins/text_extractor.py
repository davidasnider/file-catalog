import logging
import asyncio
import shutil
from typing import Dict, Any
import pdfplumber
import pytesseract
from PIL import Image
import xlrd
from hachoir.parser import createParser
from hachoir.metadata import extractMetadata

from src.core.plugin_registry import AnalyzerBase, register_analyzer
from src.core.config import config

logger = logging.getLogger(__name__)

SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/bmp", "image/tiff"}


@register_analyzer(name="TextExtractor", depends_on=[], version="1.3")
class TextExtractorPlugin(AnalyzerBase):
    """
    Extracts raw text from common document types (PDFs, docs) and images (OCR).
    """

    def should_run(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> bool:
        if config.use_document_ai:
            supported_docai_prefixes = {
                "application/pdf",
                "image/",
                "application/vnd.openxmlformats-officedocument",
            }
            if any(mime_type.startswith(p) for p in supported_docai_prefixes):
                logger.debug(
                    f"Skipping TextExtractor for {file_path} because Document AI is enabled."
                )
                return False
        return True

    async def analyze(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Extract text based on the detected MIME type."""
        logger.info(f"Extracting text for {file_path}")

        extracted_text = ""

        try:
            if mime_type == "text/plain":
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    extracted_text = f.read()
            elif mime_type == "text/html":
                from bs4 import BeautifulSoup

                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    soup = BeautifulSoup(f, "html.parser")
                    extracted_text = soup.get_text(separator="\n", strip=True)
            elif mime_type == "application/pdf":
                with pdfplumber.open(file_path) as pdf:
                    pages_text = []
                    for page in pdf.pages:
                        text = page.extract_text()
                        if text:
                            pages_text.append(text)
                    extracted_text = "\n\n".join(pages_text)
            elif (
                mime_type
                == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ):
                import docx

                doc = docx.Document(file_path)
                extracted_text = "\n".join([p.text for p in doc.paragraphs])
            elif mime_type in SUPPORTED_IMAGE_TYPES:
                logger.info(f"Running OCR on {file_path}")
                with Image.open(file_path) as img:
                    extracted_text = pytesseract.image_to_string(img)
            elif mime_type == "text/rtf":
                from striprtf.striprtf import rtf_to_text

                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    extracted_text = rtf_to_text(f.read())
            elif mime_type == "application/mbox":
                import mailbox
                import contextlib

                with contextlib.closing(mailbox.mbox(file_path)) as mbox:
                    texts = []
                    for i, msg in enumerate(mbox):
                        if msg.is_multipart():
                            for part in msg.walk():
                                if part.get_content_type() == "text/plain":
                                    payload = part.get_payload(decode=True)
                                    if payload:
                                        charset = part.get_content_charset() or "utf-8"
                                        try:
                                            text = payload.decode(
                                                charset, errors="replace"
                                            )
                                        except LookupError:
                                            text = payload.decode(
                                                "utf-8", errors="replace"
                                            )
                                        texts.append(text)
                        else:
                            payload = msg.get_payload(decode=True)
                            if payload:
                                charset = msg.get_content_charset() or "utf-8"
                                try:
                                    text = payload.decode(charset, errors="replace")
                                except LookupError:
                                    text = payload.decode("utf-8", errors="replace")
                                texts.append(text)
                    extracted_text = "\n\n".join(texts)
            elif mime_type == "application/vnd.ms-outlook":
                import extract_msg

                with extract_msg.openMsg(file_path) as msg:
                    extracted_text = msg.body if msg.body else ""
            elif mime_type == "audio/x-wav":
                logger.debug(
                    "Skipping text extraction for WAV audio; "
                    "audio transcription should be handled by the audio_transcriber analyzer."
                )
            elif mime_type == "chemical/x-cdx":
                import re

                with open(file_path, "rb") as f:
                    content = f.read()
                # Extract printable strings as a fallback for binary CDX files (ASCII range)
                strings = re.findall(b"[\x20-\x7e]{4,}", content)
                extracted_text = "\n".join(
                    [s.decode("ascii", errors="ignore") for s in strings]
                )
            elif mime_type == "application/msword":
                antiword_path = shutil.which("antiword")
                if antiword_path:
                    try:
                        # Use asyncio to run the subprocess without blocking the event loop
                        proc = await asyncio.create_subprocess_exec(
                            antiword_path,
                            "-t",
                            file_path,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        try:
                            # Add a 30-second timeout to handle corrupt or hung documents
                            stdout, stderr = await asyncio.wait_for(
                                proc.communicate(), timeout=30.0
                            )
                            if proc.returncode == 0:
                                extracted_text = stdout.decode(
                                    "utf-8", errors="replace"
                                )
                            else:
                                logger.error(
                                    f"Antiword failed for {file_path} (code {proc.returncode}): {stderr.decode('utf-8', errors='replace')}"
                                )
                                extracted_text = ""
                        except asyncio.TimeoutError:
                            logger.error(f"Antiword TIMED OUT for {file_path}")
                            proc.kill()
                            await proc.wait()
                            extracted_text = ""
                    except Exception as e:
                        logger.error(f"Failed to run antiword for {file_path}: {e}")
                        extracted_text = ""
                else:
                    logger.warning(
                        f"Skipping {file_path}: 'antiword' is not installed. "
                        "Please install 'antiword' and ensure it is on your PATH for legacy .doc support."
                    )
                    extracted_text = ""
            elif mime_type == "application/vnd.ms-excel":
                try:
                    workbook = xlrd.open_workbook(file_path)
                    all_text = []
                    for sheet in workbook.sheets():
                        all_text.append(f"Sheet: {sheet.name}")
                        for row_idx in range(sheet.nrows):
                            row_values = [
                                str(val)
                                for val in sheet.row_values(row_idx)
                                if val is not None
                            ]
                            all_text.append(" ".join(row_values))
                    extracted_text = "\n".join(all_text)
                except Exception as e:
                    logger.error(f"xlrd failed for {file_path}: {e}")
                    extracted_text = ""
            elif mime_type == "application/vnd.ms-powerpoint":
                try:
                    parser = createParser(file_path)
                    if parser:
                        with parser:
                            metadata = extractMetadata(parser)
                            if metadata:
                                plaintext = metadata.exportPlaintext()
                                if isinstance(plaintext, str):
                                    extracted_text = plaintext
                                else:
                                    try:
                                        extracted_text = "\n".join(plaintext)
                                    except TypeError:
                                        extracted_text = str(plaintext)
                            else:
                                logger.warning(f"No metadata found for {file_path}")
                                extracted_text = ""
                    else:
                        logger.warning(f"Hachoir could not parse {file_path}")
                        extracted_text = ""
                except Exception as e:
                    logger.error(f"Hachoir failed for {file_path}: {e}")
                    extracted_text = ""
            elif mime_type == "message/rfc822":
                import email
                from email import policy

                try:
                    with open(file_path, "rb") as f:
                        msg = email.message_from_binary_file(f, policy=policy.default)
                        subject = msg.get("subject", "")
                        from_addr = msg.get("from", "")
                        to_addr = msg.get("to", "")
                        date = msg.get("date", "")

                        body = ""
                        if msg.is_multipart():
                            for part in msg.walk():
                                if part.get_content_type() == "text/plain":
                                    body = part.get_content()
                                    break
                        else:
                            body = msg.get_content()

                        extracted_text = f"Subject: {subject}\nFrom: {from_addr}\nTo: {to_addr}\nDate: {date}\n\n{body}"
                except Exception as e:
                    logger.error(f"Email parsing failed for {file_path}: {e}")
                    extracted_text = ""
            elif mime_type == "application/vnd.wordperfect":
                import re

                try:
                    # Legacy WordPerfect files are complex; without wpd2text,
                    # we perform a robust string extraction as a fallback.
                    with open(file_path, "rb") as f:
                        content = f.read()
                    # Extract printable sequences of 4+ characters
                    strings = re.findall(b"[\x20-\x7e]{4,}", content)
                    extracted_text = "\n".join(
                        [s.decode("ascii", errors="ignore") for s in strings]
                    )
                    logger.info(
                        f"Extracted {len(strings)} strings from WordPerfect file"
                    )
                except Exception as e:
                    logger.error(
                        f"WordPerfect raw extraction failed for {file_path}: {e}"
                    )
                    extracted_text = ""
            else:
                # We skip non-textual types or types we don't support yet, returning empty text.
                logger.debug(
                    f"Skipping text extraction for unsupported mime type: {mime_type}"
                )

            return {
                "text": extracted_text.strip(),
                "extracted": bool(extracted_text.strip()),
                "source": "text_extractor",
            }

        except Exception as e:
            logger.error(f"Failed to extract text from {file_path}: {e}")
            raise Exception(f"Text extraction failed: {str(e)}")
