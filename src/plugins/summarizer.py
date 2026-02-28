import logging
from typing import Dict, Any

from src.core.plugin_registry import AnalyzerBase, register_analyzer
from src.llm.llama_cpp import LlamaCppProvider

logger = logging.getLogger(__name__)

# This would ideally be loaded from a configuration file or .env
MODEL_PATH = "models/Llama-3-8B.gguf"

provider = None


def get_llm_provider():
    """Lazy initialize the LLM to avoid blocking quick startup or imports."""
    global provider
    if provider is None:
        try:
            provider = LlamaCppProvider(model_path=MODEL_PATH, n_ctx=8192)
        except FileNotFoundError:
            logger.warning(
                f"Llama model not found at {MODEL_PATH}. Skipping LLM initialization."
            )
            return "MISSING_MODEL"
        except ImportError:
            logger.warning(
                "llama-cpp-python not installed. Skipping LLM initialization."
            )
            return "MISSING_LIBRARY"
    return provider


@register_analyzer(name="Summarizer", depends_on=["TextExtractor"], version="1.2")
class SummarizerPlugin(AnalyzerBase):
    """
    Summarizes the extracted text from a document using a local LLM.
    """

    async def analyze(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info(f"Summarizing document {file_path}")

        # 1. Fetch text from upstream Extractors Context
        text_data = context.get("TextExtractor", {})

        extracted_text = text_data.get("text", "")

        if not extracted_text:
            logger.debug(f"No text extracted for {file_path}. Skipping summarization.")
            return {"summary": "", "skipped": True, "error": "No text extracted."}

        # Truncate text aggressively for local context limits (MVP behavior)
        max_chars = 15000
        if len(extracted_text) > max_chars:
            extracted_text = extracted_text[:max_chars] + "... [TRUNCATED]"

        # 2. Get LLM Instance
        llm = get_llm_provider()
        if not llm:
            return {
                "summary": "",
                "skipped": True,
                "error": "LLM Provider uninitialized",
            }
        elif llm == "MISSING_MODEL":
            return {
                "summary": "",
                "skipped": True,
                "error": f"Llama model not found at {MODEL_PATH}",
            }
        elif llm == "MISSING_LIBRARY":
            return {
                "summary": "",
                "skipped": True,
                "error": "llama-cpp-python is not installed",
            }

        prompt = f"""
You are an expert document summarizer analyzing a local digital archive. Read the following text extracted from a file and provide a concise, 3-sentence summary of the core content.

Text:
{extracted_text}

Summary:
"""

        try:
            summary_response = await llm.generate(
                prompt, max_tokens=256, temperature=0.3
            )
            return {
                "summary": summary_response.strip(),
                "skipped": False,
                "model": MODEL_PATH,
            }

        except Exception as e:
            logger.error(f"Failed to generate summary for {file_path}: {e}")
            raise Exception(f"Summarization execution failed: {str(e)}")
