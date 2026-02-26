import json
import logging
from typing import Dict, Any

from src.core.plugin_registry import AnalyzerBase, register_analyzer
from src.plugins.summarizer import get_llm_provider

logger = logging.getLogger(__name__)


@register_analyzer(name="EstateAnalyzer", depends_on=["TextExtractor", "OCRExtractor"])
class EstateAnalyzerPlugin(AnalyzerBase):
    """
    Analyzes extracted text to find estate, legal, or financial relevance.
    """

    async def analyze(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info(f"Checking estate relevance for {file_path}")

        # 1. Fetch text from upstream Extractors Context
        text_data = context.get("TextExtractor", {})
        ocr_data = context.get("OCRExtractor", {})

        extracted_text = text_data.get("text", "")
        if not extracted_text:
            extracted_text = ocr_data.get("text", "")

        if not extracted_text:
            return {
                "is_estate_document": False,
                "analysis": "No text content found",
                "skipped": True,
            }

        # Truncate text aggressively for local context limits
        max_chars = 10000
        if len(extracted_text) > max_chars:
            extracted_text = extracted_text[:max_chars] + "..."

        # 2. Get LLM Instance
        llm = get_llm_provider()
        if not llm:
            return {
                "is_estate_document": False,
                "skipped": True,
                "error": "LLM Provider uninitialized",
            }

        prompt = f"""
You are a legal AI checking file contents for an estate planning system.
Read the text below and determine if this file is critical for an estate plan, financial archive, or legal records (e.g., Will, Trust, Deed, Bank Statement, Tax Return, Life Insurance).

Respond ONLY with valid JSON with exactly two fields:
"is_estate_document": true or false
"reasonging": "A 1 sentence explanation of why it is or isn't relevant."

Text:
{extracted_text}
"""

        try:
            # We urge the LLM towards JSON. Advanced models support forced schemas.
            # Local models might sometimes prepend markdown or extra text.
            llm_response = await llm.generate(prompt, max_tokens=150, temperature=0.1)

            # Very basic cleanup of output for MVP parsing
            clean_str = llm_response.strip()
            if "```json" in clean_str:
                clean_str = clean_str.split("```json")[-1].split("```")[0].strip()
            elif "```" in clean_str:
                clean_str = clean_str.split("```")[-1].split("```")[0].strip()

            try:
                parsed_json = json.loads(clean_str)
            except json.JSONDecodeError:
                # Fallback if the LLM completely fails at JSON
                logger.warning(
                    f"Failed to parse JSON from LLM for estate check: {clean_str}"
                )
                parsed_json = {
                    "is_estate_document": False,
                    "reasoning": "Failed to parse LLM response.",
                    "raw_response": clean_str,
                }

            parsed_json["skipped"] = False
            return parsed_json

        except Exception as e:
            logger.error(f"Failed to generate estate analysis for {file_path}: {e}")
            raise Exception(f"Estate Analysis failed: {str(e)}")
