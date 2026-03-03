import logging
from typing import Dict, Any

from src.core.plugin_registry import AnalyzerBase, register_analyzer
from src.llm.factory import get_llm_provider

logger = logging.getLogger(__name__)


@register_analyzer(
    name="EstateAnalyzer", depends_on=["TextExtractor", "Router"], version="1.4"
)
class EstateAnalyzerPlugin(AnalyzerBase):
    """
    Analyzes extracted text to find estate, legal, or financial relevance.
    Crucially, this now relies on the Router to conditionally execute only for Legal/Estate documents.
    """

    def should_run(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> bool:
        router_data = context.get("Router", {})
        category = router_data.get("category", "")
        # Only explicitly run the heavy Estate modeling if the Router flagged it
        return category == "Legal/Estate"

    async def analyze(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info(f"Checking estate relevance for {file_path}")

        # 1. Fetch text from upstream Extractors Context
        text_data = context.get("TextExtractor", {})

        extracted_text = text_data.get("text", "")

        if not extracted_text:
            return {
                "is_estate_document": False,
                "analysis": "No text content found",
                "skipped": True,
                "error": "No text extracted.",
            }

        # Truncate text aggressively for local context limits
        max_chars = 10000
        if len(extracted_text) > max_chars:
            extracted_text = extracted_text[:max_chars] + "..."

        # 2. Get LLM Instance
        llm = get_llm_provider(is_vision=False)
        if not llm:
            return {
                "is_estate_document": False,
                "skipped": True,
                "error": "LLM Provider uninitialized",
            }
        elif llm == "MISSING_MODEL":
            return {
                "is_estate_document": False,
                "skipped": True,
                "error": "Llama model not found at models/Llama-3-8B.gguf",
            }
        elif llm == "MISSING_LIBRARY":
            return {
                "is_estate_document": False,
                "skipped": True,
                "error": "llama-cpp-python is not installed",
            }

        prompt = f"""
You are a legal AI checking file contents for an estate planning system.
Read the text below and determine if this file is critical for an estate plan, financial archive, or legal records (e.g., Will, Trust, Deed, Bank Statement, Tax Return, Life Insurance).

Respond ONLY with valid JSON with exactly two fields:
"is_estate_document": true or false
"reasoning": "A 1 sentence explanation of why it is or isn't relevant."

Desired Output Format (Valid JSON ONLY):
{{
  "is_estate_document": true,
  "reasoning": "This document appears to be a Last Will and Testament."
}}

Text:
{extracted_text}
"""

        try:
            # We urge the LLM towards JSON. Advanced models support forced schemas.
            llm_response = await llm.generate(
                prompt,
                max_tokens=150,
                temperature=0.0,
                response_format={
                    "type": "json_object",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "is_estate_document": {"type": "boolean"},
                            "reasoning": {"type": "string"},
                        },
                        "required": ["is_estate_document", "reasoning"],
                    },
                },
            )

            from src.core.text_utils import repair_and_load_json

            parsed_json = repair_and_load_json(llm_response)
            if not parsed_json:
                # Fallback if parsing failed completely
                logger.warning(
                    f"Failed to parse JSON from LLM for estate check: {llm_response}"
                )
                parsed_json = {
                    "is_estate_document": False,
                    "reasoning": "Failed to parse LLM response.",
                }

            parsed_json["skipped"] = False
            return parsed_json

        except Exception as e:
            logger.error(f"Failed to generate estate analysis for {file_path}: {e}")
            raise Exception(f"Estate Analysis failed: {str(e)}")
