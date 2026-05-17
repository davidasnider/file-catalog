import logging
from typing import Dict, Any

from src.core.plugin_registry import AnalyzerBase, register_analyzer
from src.llm.factory import get_llm_provider
from src.core.config import config
from src.core.text_utils import get_all_extracted_text
from src.core.analyzer_names import (
    TEXT_EXTRACTOR_NAME,
    SUMMARIZER_NAME,
    DOCUMENT_AI_EXTRACTOR_NAME,
    AUDIO_TRANSCRIBER_NAME,
    VISION_ANALYZER_NAME,
    VIDEO_ANALYZER_NAME,
    EMAIL_PARSER_NAME,
)

logger = logging.getLogger(__name__)


@register_analyzer(
    name=SUMMARIZER_NAME,
    depends_on=[
        TEXT_EXTRACTOR_NAME,
        DOCUMENT_AI_EXTRACTOR_NAME,
        AUDIO_TRANSCRIBER_NAME,
        VISION_ANALYZER_NAME,
        VIDEO_ANALYZER_NAME,
        EMAIL_PARSER_NAME,
    ],
    version="1.5",
)
class SummarizerPlugin(AnalyzerBase):
    """
    Summarizes the extracted text from a document using a local LLM.
    """

    async def analyze(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info(f"Summarizing document {file_path}")

        # 1. Fetch text from upstream Extractors Context
        extracted_text = get_all_extracted_text(context)

        if not extracted_text:
            logger.debug(f"No text extracted for {file_path}. Skipping summarization.")
            return {"summary": "", "skipped": True, "error": "No text extracted."}

        # If text is large, we skip the standard summarizer and rely on DeepSummarizer
        # to avoid providing a truncated/incomplete summary.
        max_chars = 20000
        if len(extracted_text) > max_chars:
            logger.info(
                f"Text too large for standard summarizer ({len(extracted_text)} chars). Skipping in favor of DeepSummarizer."
            )
            return {
                "summary": "",
                "skipped": True,
                "reason": "text_too_large",
            }

        # 2. Get LLM Instance
        llm = get_llm_provider(is_vision=False)
        if not llm:
            return {
                "summary": "",
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
                "summary": "",
                "skipped": True,
                "error": error_msg,
            }

        prompt = f"""
You are an expert document summarizer analyzing a local digital archive. Read the following text extracted from a file and provide a concise, 3-sentence summary of the core content.

CRITICAL INSTRUCTIONS:
1. Return ONLY the 3-sentence summary.
2. Accurately identify the roles of individuals (e.g., strictly distinguish between the customer/account holder and service providers/technicians). Do not conflate names with incorrect titles.
3. Ensure absolute factual alignment with the source text. Do not make assumptions.
4. DO NOT output any thinking process. NO <think> tags. NO "Here is a thinking process".
5. Do NOT include any conversational filler, preambles, or introductory text.
6. Begin exactly with the first sentence of the summary.

Text:
{extracted_text}
"""

        try:
            # We pass the maximum supported tokens because reasoning models (like Qwen) use extensive tokens for thinking
            # before they output the short summary.
            model_max = await llm.get_max_output_tokens()
            summary_response = await llm.generate(
                prompt, max_tokens=model_max, temperature=0.3
            )

            if not summary_response:
                raise ValueError("LLM returned an empty response during summarization.")

            # Strip any leaked thinking blocks
            cleaned_summary = self._strip_thinking(summary_response)

            if not cleaned_summary:
                raise ValueError(
                    "LLM response was empty after stripping thinking blocks."
                )

            return {
                "summary": cleaned_summary,
                "skipped": False,
                "model": getattr(llm, "model_name", "Unknown Model"),
                "prompt": prompt,
            }

        except Exception as e:
            logger.error(f"Failed to generate summary for {file_path}: {e}")
            raise Exception(f"Summarization execution failed: {str(e)}")
