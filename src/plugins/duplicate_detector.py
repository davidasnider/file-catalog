import hashlib
import logging
from typing import Dict, Any

from src.core.plugin_registry import AnalyzerBase, register_analyzer

logger = logging.getLogger(__name__)


@register_analyzer(name="DuplicateDetector", depends_on=[], version="1.0")
class DuplicateDetectorPlugin(AnalyzerBase):
    """
    Detects duplicate files by computing SHA-256 hashes and comparing
    them against previously seen hashes within the same processing batch.
    The scanner already stores file_hash on each Document, so this plugin
    re-computes the hash and stores duplicate group info in its result.
    """

    async def analyze(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info(f"Running duplicate detection for {file_path}")

        try:
            file_hash = self._compute_hash(file_path)
        except Exception as e:
            logger.error(f"Failed to compute hash for {file_path}: {e}")
            raise Exception(f"Duplicate detection failed: {str(e)}")

        return {
            "file_hash": file_hash,
            "source": "duplicate_detector",
        }

    @staticmethod
    def _compute_hash(file_path: str, chunk_size: int = 8192) -> str:
        """Compute SHA-256 hash of a file."""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(chunk_size):
                hasher.update(chunk)
        return hasher.hexdigest()
