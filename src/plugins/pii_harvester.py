import logging
from typing import Dict, Any

from src.core.plugin_registry import AnalyzerBase, register_analyzer
from src.llm.factory import get_llm_provider

logger = logging.getLogger(__name__)

# Using the configured LLM for general extraction


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

        from src.core.text_utils import get_all_extracted_text

        extracted_text = get_all_extracted_text(context)
        return len(extracted_text) > 50

    async def analyze(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info(f"Harvesting PII/Secrets for {file_path}")

        from src.core.text_utils import get_all_extracted_text

        extracted_text = get_all_extracted_text(context)

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
        CRITICAL: If none are found, return empty lists. DO NOT invent placeholder data.
        Output valid JSON ONLY.

        Desired Output Format (Valid JSON ONLY):
        {{
          "names": [],
          "emails": [],
          "addresses": [],
          "secrets": []
        }}

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

            from src.core.text_utils import repair_and_load_json

            parsed = repair_and_load_json(response)
            if not parsed:
                parsed = {"names": [], "emails": [], "addresses": [], "secrets": []}
            else:
                parsed.setdefault("names", [])
                parsed.setdefault("emails", [])
                parsed.setdefault("addresses", [])
                parsed.setdefault("secrets", [])
            return {"pii": parsed, "skipped": False, "method": "llm_json_expert"}
        except Exception as e:
            logger.error(f"Failed to harvest PII for {file_path}: {e}")
            return {"pii": {}, "skipped": True, "error": str(e)}
