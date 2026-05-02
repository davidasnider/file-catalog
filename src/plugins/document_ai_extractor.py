import logging
import os
from typing import Dict, Any

from src.core.plugin_registry import AnalyzerBase, register_analyzer
from src.core.config import config
from src.core.analyzer_names import DOCUMENT_AI_EXTRACTOR_NAME

logger = logging.getLogger(__name__)

try:
    from google.api_core.client_options import ClientOptions
    from google.cloud import documentai

    HAS_DOC_AI = True
except ImportError:
    HAS_DOC_AI = False


@register_analyzer(name=DOCUMENT_AI_EXTRACTOR_NAME, depends_on=[], version="1.0")
class DocumentAIExtractorPlugin(AnalyzerBase):
    """
    Extracts text from documents using Google Cloud Document AI.
    Runs selectively if configured to bypass local extraction.
    """

    def should_run(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> bool:
        # Only run if Document AI is explicitly enabled in config and the Processor ID is provided
        if not config.use_document_ai or not os.getenv("DOC_AI_PROCESSOR_ID"):
            return False

        # Document AI supports PDF, TIFF, GIF, DOCX, JPEG, PNG, etc.
        supported_prefixes = {
            "application/pdf",
            "image/",
            "application/vnd.openxmlformats-officedocument",
        }
        return any(mime_type.startswith(p) for p in supported_prefixes)

    async def analyze(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Extract text using Google Cloud Document AI API."""
        if not HAS_DOC_AI:
            logger.error(
                "google-cloud-documentai is not installed but Document AI is enabled."
            )
            return {
                "text": "",
                "extracted": False,
                "error": "Missing Document AI library",
            }

        logger.info(f"Extracting text via Google Document AI for {file_path}")

        project_id = config.google_cloud_project
        # Document AI uses multi-region locations ("us", "eu"), not Vertex AI
        # regions like "us-central1". Prefer a dedicated setting if available,
        # then fall back to a general Google Cloud location or env, and default to "us".
        raw_location = (
            getattr(config, "document_ai_location", None)
            or getattr(config, "google_cloud_location", None)
            or os.getenv("DOCUMENT_AI_LOCATION")
            or "us"
        )

        # Normalise common regional locations (e.g. "us-central1" -> "us").
        location = raw_location.lower()
        if location.startswith("us-"):
            location = "us"
        elif location.startswith("eu-"):
            location = "eu"

        # If, after normalisation, the location is not a known multi-region,
        # log a warning and fall back to "us" to avoid misconfigured endpoints.
        if location not in ("us", "eu"):
            logger.warning(
                "Invalid or unsupported Document AI location '%s'; "
                "falling back to 'us'.",
                raw_location,
            )
            location = "us"

        if not project_id:
            logger.error("google_cloud_project is not configured for Document AI.")
            return {"text": "", "extracted": False, "error": "Missing project config"}

        # For basic extraction, we can use the default OCR processor (often pre-created or we can use the foundation model)
        # Note: In a real production setup, the user needs to create a Processor in Google Cloud Console
        # and provide the processor ID. We will attempt to use a general layout/OCR processor if available,
        # or require it in config. For MVP, we assume a "processor_id" is configured or we use default OCR.

        # We need a processor ID. Let's add it to config implicitly by checking env, or log an error if missing.
        processor_id = os.getenv("DOC_AI_PROCESSOR_ID")
        if not processor_id:
            logger.warning(
                "DOC_AI_PROCESSOR_ID env var is missing. Document AI needs a specific processor ID."
            )
            return {
                "text": "",
                "extracted": False,
                "error": "DOC_AI_PROCESSOR_ID not found in environment.",
            }

        try:
            # You must set the api_endpoint if you use a location other than 'us'.
            opts = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
            client = documentai.DocumentProcessorServiceClient(client_options=opts)

            name = client.processor_path(project_id, location, processor_id)

            with open(file_path, "rb") as file:
                image_content = file.read()

            raw_document = documentai.RawDocument(
                content=image_content, mime_type=mime_type
            )

            request = documentai.ProcessRequest(name=name, raw_document=raw_document)

            # In a fully async system, we'd run this blocking call in an executor.
            import asyncio

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, client.process_document, request)

            document = result.document
            extracted_text = document.text

            return {
                "text": extracted_text.strip(),
                "extracted": bool(extracted_text.strip()),
                "source": "document_ai_extractor",
            }

        except Exception as e:
            logger.error(
                f"Failed to extract text using Document AI for {file_path}: {e}"
            )
            return {
                "text": "",
                "extracted": False,
                "error": f"Document AI extraction failed: {e}",
            }
