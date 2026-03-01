import logging
import statistics
from typing import Dict, Any

import pytesseract
from PIL import Image

from src.core.plugin_registry import AnalyzerBase, register_analyzer

logger = logging.getLogger(__name__)

SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/bmp", "image/tiff"}

# Confidence threshold below which a document is flagged for review
REVIEW_THRESHOLD = 60.0


@register_analyzer(
    name="OCRConfidenceScorer", depends_on=["TextExtractor"], version="1.0"
)
class OCRConfidenceScorerPlugin(AnalyzerBase):
    """
    Scores OCR quality for image-based documents using pytesseract's
    word-level confidence data. Flags low-confidence extractions for
    manual review.
    """

    def should_run(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> bool:
        return mime_type in SUPPORTED_IMAGE_TYPES

    async def analyze(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info(f"Scoring OCR confidence for {file_path}")

        try:
            with Image.open(file_path) as img:
                data = pytesseract.image_to_data(
                    img, output_type=pytesseract.Output.DICT
                )

            # Filter to actual words with valid confidence scores
            # pytesseract returns -1 for non-word elements
            confidences = [
                int(conf)
                for conf, text in zip(data["conf"], data["text"])
                if int(conf) >= 0 and text.strip()
            ]

            if not confidences:
                return {
                    "mean_confidence": 0.0,
                    "median_confidence": 0.0,
                    "total_words": 0,
                    "low_confidence_words": 0,
                    "needs_review": True,
                    "confidence_distribution": {},
                    "source": "ocr_confidence_scorer",
                }

            mean_conf = round(statistics.mean(confidences), 2)
            median_conf = round(statistics.median(confidences), 2)
            low_conf_count = sum(1 for c in confidences if c < REVIEW_THRESHOLD)

            # Build a simple distribution (buckets of 10)
            distribution = {}
            for bucket_start in range(0, 100, 10):
                bucket_label = f"{bucket_start}-{bucket_start + 9}"
                distribution[bucket_label] = sum(
                    1 for c in confidences if bucket_start <= c < bucket_start + 10
                )
            # 100 exactly
            distribution["100"] = sum(1 for c in confidences if c == 100)

            return {
                "mean_confidence": mean_conf,
                "median_confidence": median_conf,
                "total_words": len(confidences),
                "low_confidence_words": low_conf_count,
                "needs_review": mean_conf < REVIEW_THRESHOLD,
                "confidence_distribution": distribution,
                "source": "ocr_confidence_scorer",
            }

        except Exception as e:
            logger.error(f"OCR confidence scoring failed for {file_path}: {e}")
            raise Exception(f"OCR confidence scoring failed: {str(e)}")
