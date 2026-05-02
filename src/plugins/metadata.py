import os
import datetime
import logging
from typing import Dict, Any

from src.core.plugin_registry import AnalyzerBase, register_analyzer
from src.core.analyzer_names import METADATA_EXTRACTOR_NAME

logger = logging.getLogger(__name__)


@register_analyzer(name=METADATA_EXTRACTOR_NAME, depends_on=[])
class MetadataExtractorPlugin(AnalyzerBase):
    """
    A basic plugin that extracts simple file system metadata.
    Does not depend on any other plugins.
    """

    async def analyze(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Extracts size, creation time, modification time."""
        logger.info(f"Extracting metadata for {file_path}")

        try:
            stat_info = os.stat(file_path)

            # Formatting timestamps
            c_time = datetime.datetime.fromtimestamp(stat_info.st_ctime).isoformat()
            m_time = datetime.datetime.fromtimestamp(stat_info.st_mtime).isoformat()

            return {
                "file_size_bytes": stat_info.st_size,
                "created_at": c_time,
                "modified_at": m_time,
                "mime_type": mime_type,  # Explicitly copy this in for downstream visibility
            }

        except OSError as e:
            logger.error(f"Failed to extract stat metadata for {file_path}: {e}")
            raise Exception(f"Metadata extraction failed: {str(e)}")
