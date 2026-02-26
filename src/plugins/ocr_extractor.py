import logging
from typing import Dict, Any
import pytesseract
from PIL import Image

from src.core.plugin_registry import AnalyzerBase, register_analyzer

logger = logging.getLogger(__name__)

SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/bmp", "image/tiff"}


@register_analyzer(name="OCRExtractor", depends_on=[])
class OCRExtractorPlugin(AnalyzerBase):
    """
    Extracts text from images using Tesseract OCR.
    """

    async def analyze(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Run OCR on image files to extract textual content."""
        if mime_type not in SUPPORTED_IMAGE_TYPES:
            logger.debug(f"Skipping OCR for non-image type: {mime_type}")
            return {
                "text": "",
                "extracted": False,
                "source": "ocr_extractor",
                "skipped": True,
            }

        logger.info(f"Running OCR on {file_path}")
        extracted_text = ""

        try:
            # Note: in an async environment, pytesseract (which uses subprocess)
            # could block the event loop slightly, but since task_engine executes plugins sequentially
            # in its own asyncio context without ThreadPoolExecutor wrapping yet, this limits concurrency.
            # In a robust V3 version, we would wrap this in asyncio.to_thread.
            with Image.open(file_path) as img:
                extracted_text = pytesseract.image_to_string(img)

            return {
                "text": extracted_text.strip(),
                "extracted": bool(extracted_text.strip()),
                "source": "ocr_extractor",
            }

        except Exception as e:
            logger.error(f"Failed to run OCR on {file_path}: {e}")
            raise Exception(f"OCR execution failed: {str(e)}")
