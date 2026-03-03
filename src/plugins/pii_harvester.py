import json
import logging
from typing import Dict, Any

from src.core.plugin_registry import AnalyzerBase, register_analyzer
from src.llm.factory import get_llm_provider

logger = logging.getLogger(__name__)

# Using Llama-3-8B for general extraction (can swap to Qwen later for specialized speed)


@register_analyzer(
    name="PIIHarvester", depends_on=["TextExtractor", "Router"], version="1.0"
)
class PIIHarvesterPlugin(AnalyzerBase):
    """
    Extracts PII and secrets from document text using strict JSON schema formatting.
    This does not mask the original files.
    """

    def should_run(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> bool:
        category = context.get("Router", {}).get("category", "")
        # Images won't have text unless OCR is run. For now, skip Images/Video/Audio.
        if category in ["Image", "Video", "Audio"]:
            return False

        extracted_text = context.get("TextExtractor", {}).get("text", "")
        return len(extracted_text) > 50

    async def analyze(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info(f"Harvesting PII/Secrets for {file_path}")

        extracted_text = context.get("TextExtractor", {}).get("text", "")

        # Scrape the first ~15,000 characters for secrets
        sample_text = extracted_text[:15000]

        # 2. Get LLM Instance
        llm = get_llm_provider(is_vision=False, n_ctx=8192)
        if not llm or llm in ("MISSING_MODEL", "MISSING_LIBRARY"):
            return {
                "pii": {},
                "skipped": True,
                "error": "LLM Provider unavailable",
            }

        prompt = f"""
        You are a forensic PII extractor. Read the following text and extract all PII, names, emails, addresses, financial accounts, or secrets.
        If none are found, return empty lists.
        Output ONLY valid JSON.

        Text:
        {sample_text}
        """

        try:
            response = await llm.generate(
                prompt,
                max_tokens=250,
                temperature=0.0,
                response_format={
                    "type": "json_object",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "names": {"type": "array", "items": {"type": "string"}},
                            "emails": {"type": "array", "items": {"type": "string"}},
                            "addresses": {"type": "array", "items": {"type": "string"}},
                            "secrets": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["names", "emails", "addresses", "secrets"],
                    },
                },
            )

            clean_str = self._extract_json_from_response(response)

            parsed = json.loads(clean_str)
            return {"pii": parsed, "skipped": False, "method": "llm_json_expert"}
        except Exception as e:
            logger.error(f"Failed to harvest PII for {file_path}: {e}")
            return {"pii": {}, "skipped": True, "error": str(e)}
