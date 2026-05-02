import logging
from typing import Dict, Any

from src.core.plugin_registry import AnalyzerBase, register_analyzer
from src.llm.factory import get_llm_provider
from src.core.text_utils import get_all_extracted_text
from src.core.analyzer_names import TEXT_EXTRACTOR_NAME

logger = logging.getLogger(__name__)


@register_analyzer(
    name="Router",
    depends_on=[
        TEXT_EXTRACTOR_NAME,
        "DocumentAIExtractor",
        "audio_transcriber",
        "vision_analyzer",
        "video_analyzer",
    ],
    version="1.0",
)
class RouterPlugin(AnalyzerBase):
    """
    Classifies the document into a high-level taxonomy category using fast heuristics
    where possible, and falling back to a lightweight LLM evaluation for ambiguous text.
    """

    async def analyze(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info(f"Routing document {file_path}")

        # 1. Fast Heuristics
        fast_category = self._apply_heuristics(mime_type, file_path)
        if fast_category:
            return {"category": fast_category, "method": "heuristic"}

        # 2. LLM Fallback
        extracted_text = get_all_extracted_text(context)

        if not extracted_text:
            return {
                "category": "Unknown",
                "method": "fallback",
                "reason": "No text and unseen mime_type",
            }

        max_chars = 3000
        sample_text = extracted_text[:max_chars]

        llm = get_llm_provider(is_vision=False)
        if not llm or llm in ("MISSING_MODEL", "MISSING_LIBRARY"):
            logger.warning("LLM unavailable for routing, falling back to GenericText")
            return {"category": "GenericText", "method": "fallback_no_llm"}

        prompt = f"""
        You are a document classifier routing files for an automated pipeline.
        Examine the following text sample and assign it to exactly ONE of the following categories:
        - Legal/Estate (e.g. Will, Trust, Contract, Legal Brief)
        - Financial (e.g. Ledger, Bank Statement, Invoice)
        - Technical (e.g. Engineering spec, Server Log, scientific paper)
        - GenericText (Standard prose, correspondence, or unclassifiable)

        Desired Output Format (Valid JSON ONLY):
        {{
          "category": "Legal/Estate"
        }}

        Text:
        {sample_text}
        """

        try:
            response = await llm.generate(
                prompt,
                max_tokens=64,
                temperature=0.0,
                response_format={
                    "type": "json_object",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "category": {
                                "type": "string",
                                "enum": [
                                    "Legal/Estate",
                                    "Financial",
                                    "Technical",
                                    "GenericText",
                                ],
                            }
                        },
                        "required": ["category"],
                    },
                },
            )

            from src.core.text_utils import repair_and_load_json

            parsed = repair_and_load_json(response)
            if not parsed:
                raise ValueError("LLM response could not be parsed as JSON.")
            return {"category": parsed.get("category", "GenericText"), "method": "llm"}
        except Exception as e:
            logger.error(f"Failed to use LLM for routing {file_path}: {e}")
            return {"category": "GenericText", "method": "error_fallback"}

    def _apply_heuristics(self, mime_type: str, file_path: str) -> str | None:
        if mime_type:
            if mime_type.startswith("image/"):
                return "Image"
            if mime_type.startswith("video/"):
                return "Video"
            if mime_type.startswith("audio/"):
                return "Audio"

            code_mimes = [
                "text/x-python",
                "application/javascript",
                "text/html",
                "text/css",
                "application/json",
                "text/x-c",
                "text/x-java-source",
                "application/x-sh",
            ]
            if mime_type in code_mimes or mime_type.startswith("text/x-"):
                return "Code"

        # 2. Extension Fallback
        if file_path.endswith((".py", ".js", ".html", ".css", ".json", ".sh")):
            return "Code"

        return None
