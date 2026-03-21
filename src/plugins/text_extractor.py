import logging
from typing import Dict, Any
import pdfplumber
import pytesseract
from PIL import Image

from src.core.plugin_registry import AnalyzerBase, register_analyzer
from src.core.config import config

logger = logging.getLogger(__name__)

SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/bmp", "image/tiff"}


@register_analyzer(name="TextExtractor", depends_on=[], version="1.2")
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

                mbox = mailbox.mbox(file_path)
                texts = []
                for i, msg in enumerate(mbox):
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                payload = part.get_payload(decode=True)
                                if payload:
                                    charset = part.get_content_charset() or "utf-8"
                                    texts.append(
                                        payload.decode(charset, errors="replace")
                                    )
                    else:
                        payload = msg.get_payload(decode=True)
                        if payload:
                            charset = msg.get_content_charset() or "utf-8"
                            texts.append(payload.decode(charset, errors="replace"))
                extracted_text = "\n\n".join(texts)
            elif mime_type == "application/vnd.ms-outlook":
                import extract_msg

                with extract_msg.openMsg(file_path) as msg:
                    extracted_text = msg.body if msg.body else ""
            elif mime_type == "audio/x-wav":
                try:
                    from src.plugins.audio_transcriber import AudioTranscriberPlugin

                    transcriber = AudioTranscriberPlugin()
                    res = await transcriber.analyze(file_path, mime_type, {})
                    extracted_text = res.get("text", "")
                except (ImportError, Exception) as e:
                    logger.warning(f"Audio transcription failed in TextExtractor: {e}")
            elif mime_type == "chemical/x-cdx":
                import re

                with open(file_path, "rb") as f:
                    content = f.read()
                # Extract printable strings as a fallback for binary CDX files (ASCII range)
                strings = re.findall(b"[\x20-\x7e]{4,}", content)
                extracted_text = "\n".join(
                    [s.decode("ascii", errors="ignore") for s in strings]
                )
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
