import hashlib
import logging
from typing import Dict, Any

from src.core.plugin_registry import AnalyzerBase, register_analyzer
from src.core.analyzer_names import DUPLICATE_DETECTOR_NAME

logger = logging.getLogger(__name__)


@register_analyzer(name=DUPLICATE_DETECTOR_NAME, depends_on=[], version="1.0")
class DuplicateDetectorPlugin(AnalyzerBase):
    """
    Computes the SHA-256 hash of a file and returns it as part of the
    analysis result. Other components can use this hash to perform
    duplicate detection or grouping if needed.
    """

    def should_run(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> bool:
        """
        Skip very large files to avoid excessive I/O and CPU usage.
        Threshold: 100MB
        """
        import os

        try:
            return os.path.getsize(file_path) < 100 * 1024 * 1024
        except Exception:
            return True

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
