import logging
from typing import Dict, Any

from src.core.plugin_registry import AnalyzerBase, register_analyzer
from src.llm.factory import get_llm_provider
from src.core.config import config
from src.core.analyzer_names import (
    TEXT_EXTRACTOR_NAME,
    ESTATE_ANALYZER_NAME,
    ROUTER_NAME,
)

logger = logging.getLogger(__name__)


@register_analyzer(
    name=ESTATE_ANALYZER_NAME,
    depends_on=[TEXT_EXTRACTOR_NAME, ROUTER_NAME],
    version="1.8",
)
class EstateAnalyzerPlugin(AnalyzerBase):
    """
    Analyzes extracted text to find estate, legal, or financial relevance.
    Crucially, this now relies on the Router to conditionally execute only for Legal/Estate documents.
    """

    def should_run(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> bool:
        router_data = context.get(ROUTER_NAME, {})
        category = router_data.get("category", "")
        # Run for Legal/Estate or Financial documents as both are critical for estate archives
        return category in ["Legal/Estate", "Financial"]

    async def analyze(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info(f"Checking estate relevance for {file_path}")

        # 1. Fetch text from upstream Extractors Context
        text_data = context.get(TEXT_EXTRACTOR_NAME, {})

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
        elif isinstance(llm, str):
            provider = getattr(config, "llm_provider", None)
            model_path = getattr(config, "llm_model_path", None)
            error_msg = llm

            if llm == "MISSING_MODEL":
                if provider in ("llama", "llama_cpp"):
                    if model_path:
                        error_msg = f"Llama model not found at {model_path}"
                    else:
                        error_msg = "Llama model not found"
                else:
                    if model_path and provider:
                        error_msg = (
                            f"Model not found for provider '{provider}' at {model_path}"
                        )
                    elif provider:
                        error_msg = f"Model not found for provider '{provider}'"
                    elif model_path:
                        error_msg = f"Model not found at {model_path}"
                    else:
                        error_msg = "Model not found for configured LLM provider"
            elif llm == "MISSING_LIBRARY":
                if provider in ("llama", "llama_cpp"):
                    error_msg = "llama-cpp-python is not installed"
                else:
                    if provider:
                        error_msg = f"Required LLM library for provider '{provider}' is not installed"
                    else:
                        error_msg = "Required LLM library is not installed"
            elif llm == "PROVIDER_INIT_FAILED":
                error_msg = f"Failed to initialize LLM provider '{provider}'"

            return {
                "is_estate_document": False,
                "skipped": True,
                "error": error_msg,
            }

        prompt = f"""
You are a legal and financial forensic AI. Your ONLY job is to identify documents that are critical for an estate plan, financial archive, or legal record.

MANDATORY RULE: Any document that identifies a financial asset, bank account, certificate account, investment, or legal interest is CRITICAL for estate planning because it identifies the property that must be managed or distributed.

Is this file essential for identifying assets, liabilities, or legal rights?

CRITICAL: The following are ALWAYS TRUE:
- Legal: Wills, Trusts, Deeds, Power of Attorney, Health Directives.
- Financial: Bank Statements, Certificate Accounts (CDs), Life Insurance, Investment records, Stock certificates, Pension/401k.
- Tax/Real Estate: Tax Returns, Property tax assessments, Mortgage docs.

Respond ONLY with valid JSON with exactly two fields:
"is_estate_document": true or false
"reasoning": "A 1 sentence explanation of why it is or isn't relevant."

Desired Output Format (Valid JSON ONLY):
{{
  "is_estate_document": true,
  "reasoning": "This is a Certificate Account statement identifying a financial asset of the estate."
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
