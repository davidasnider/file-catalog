import os
import magic
import mimetypes
import logging

logger = logging.getLogger(__name__)


def detect_file_type(file_path: str) -> str:
    """
    Robustly detect the MIME type of a file.

    1. Primary method: libmagic (examines file contents/headers)
    2. Fallback method: mimetypes (examines file extension)
    3. Default: application/octet-stream

    Args:
        file_path (str): The absolute path to the file.

    Returns:
        str: The detected MIME type.
    """
    if not os.path.exists(file_path):
        logger.warning(f"File not found for type detection: {file_path}")
        return "application/octet-stream"

    mime_type = None

    try:
        # 1. Use libmagic as the primary source of truth
        mime_type = magic.from_file(file_path, mime=True)

        # FIX: If magic says it's a mailbox but it has a .txt extension, override it.
        # libmagic often misidentifies text files starting with "From " as mbox.
        if mime_type == "application/mbox" and file_path.lower().endswith(".txt"):
            mime_type = "text/plain"

        # libmagic sometimes misidentifies .wma audio files as video/x-ms-asf
        if file_path.lower().endswith(".wma"):
            return "audio/x-ms-wma"

        # libmagic sometimes returns text/plain for things that are more specific
        if mime_type != "text/plain" and mime_type != "application/octet-stream":
            return mime_type

    except Exception as e:
        logger.error(f"Error using libmagic on {file_path}: {e}")

    # 2. Fallback to mimetypes if libmagic failed or returned a generic type
    try:
        fallback_type, _ = mimetypes.guess_type(file_path)
        if fallback_type:
            # If magic said plain text but we have a more specific extension, use the extension
            if mime_type == "text/plain":
                return fallback_type

            if not mime_type or mime_type == "application/octet-stream":
                return fallback_type
    except Exception as e:
        logger.error(f"Error using mimetypes on {file_path}: {e}")

    # 3. Return what libmagic gave us if we got here, or the ultimate fallback
    return mime_type or "application/octet-stream"
