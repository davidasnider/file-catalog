import logging
from typing import Dict, Any

from src.core.plugin_registry import AnalyzerBase, register_analyzer
from src.llm.factory import get_llm_provider
from src.core.config import config
from src.core.text_utils import get_all_extracted_text

logger = logging.getLogger(__name__)


@register_analyzer(
    name="Summarizer",
    depends_on=[
        "TextExtractor",
        "DocumentAIExtractor",
        "audio_transcriber",
        "vision_analyzer",
        "video_analyzer",
    ],
    version="1.2",
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

        # Truncate text aggressively for local context limits (MVP behavior)
        max_chars = 12000
        if len(extracted_text) > max_chars:
            extracted_text = extracted_text[:max_chars] + "... [TRUNCATED]"

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

            return {
                "summary": "",
                "skipped": True,
                "error": error_msg,
            }

        prompt = f"""
You are an expert document summarizer analyzing a local digital archive. Read the following text extracted from a file and provide a concise, 3-sentence summary of the core content.

CRITICAL INSTRUCTION: Return ONLY the 3-sentence summary. Do NOT include any conversational filler, preambles, or introductory text like "Here is a summary". Begin exactly with the first sentence of the summary.

Text:
{extracted_text}
"""

        try:
            summary_response = await llm.generate(
                prompt, max_tokens=150, temperature=0.3
            )
            return {
                "summary": summary_response.strip(),
                "skipped": False,
                "model": getattr(llm, "model_name", "Unknown Model"),
            }

        except Exception as e:
            logger.error(f"Failed to generate summary for {file_path}: {e}")
            raise Exception(f"Summarization execution failed: {str(e)}")
