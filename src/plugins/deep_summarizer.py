import logging
from typing import Dict, Any

from src.core.plugin_registry import AnalyzerBase, register_analyzer
from src.llm.factory import get_llm_provider

logger = logging.getLogger(__name__)

# Reusing the Llama-3-8B model for Map-Reduce summarization
MODEL_PATH = "models/Llama-3-8B.gguf"


@register_analyzer(
    name="DeepSummarizer",
    depends_on=["TextExtractor", "Router", "Summarizer"],
    version="1.0",
)
class DeepSummarizerPlugin(AnalyzerBase):
    """
    Performs Map-Reduce extensive summarization on large documents exceeding the standard context window.
    """

    def should_run(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> bool:
        text_data = context.get("TextExtractor", {})
        extracted_text = text_data.get("text", "")
        # Only trigger Deep Summarization for large texts (> 20,000 characters)
        if len(extracted_text) < 20000:
            return False

        router_data = context.get("Router", {})
        category = router_data.get("category", "")
        # Optionally restrict to important categories, but for now we'll do it for all large text docs
        # where deep insight is needed.
        if category in ["Image", "Video", "Audio"]:
            return False

        return True

    async def analyze(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info(f"Starting Map-Reduce Deep Summarization for {file_path}")

        extracted_text = context.get("TextExtractor", {}).get("text", "")

        # We pass n_ctx just in case the factory/manager respects it
        llm = get_llm_provider(is_vision=False, n_ctx=8192)
        if not llm or llm in ("MISSING_MODEL", "MISSING_LIBRARY"):
            return {
                "extensive_summary": "",
                "skipped": True,
                "model": getattr(llm, "model_name", "Unknown Model"),
                "error": "LLM Provider unavailable for deep summarization",
            }

        # 1. Chunking
        chunk_size = 15000  # Conservative size to fit ~3.5k tokens plus prompts
        chunks = [
            extracted_text[i : i + chunk_size]
            for i in range(0, len(extracted_text), chunk_size)
        ]

        logger.info(
            f"Document {file_path} split into {len(chunks)} chunks for Map-Reduce."
        )

        # 2. Map Phase: Summarize each chunk
        chunk_summaries = []
        for i, chunk in enumerate(chunks):
            prompt = f"""
            You are analyzing a portion of a massive document. Read the following text chunk and summarize the main points, facts, and events within it. Do not miss any critical details.

            TEXT CHUNK {i + 1}/{len(chunks)}:
            {chunk}

            SUMMARY:
            """
            try:
                # Setting higher max_tokens to capture extensive details
                response = await llm.generate(prompt, max_tokens=1200, temperature=0.2)
                chunk_summaries.append(response.strip())
            except Exception as e:
                logger.error(f"Error summarizing chunk {i + 1} for {file_path}: {e}")
                # We can continue to reduce the chunks we successfully mapped
                continue

        if not chunk_summaries:
            return {
                "extensive_summary": "",
                "skipped": True,
                "error": "Failed to generate any chunk summaries during Map phase.",
            }

        # 3. Reduce Phase: Combine chunk summaries
        combined_summaries = "\n\n".join(
            [f"Part {j + 1}: {s}" for j, s in enumerate(chunk_summaries)]
        )

        # If the combined summaries are still too large, we might need a recursive Map-Reduce.
        # But for early MVP, one pass reduce is sufficient.
        final_prompt = f"""
        You are finalizing a deep summarization task. Below are the sequential summaries of different parts of a massive document.
        Synthesize these parts into a single, cohesive, extensive summary that fully explains what this document is about, highlighting key terms, legal implications, financial data, or important narratives.
        Write a professional, comprehensive overview.

        DOCUMENT PARTS:
        {combined_summaries}

        FINAL EXTENSIVE SUMMARY:
        """

        try:
            final_response = await llm.generate(
                final_prompt, max_tokens=3000, temperature=0.3
            )
            return {
                "extensive_summary": final_response.strip(),
                "summary": final_response.strip(),  # duplicate for UI backward compatibility
                "skipped": False,
                "chunks_processed": len(chunk_summaries),
                "model": getattr(llm, "model_name", "Unknown Deep Model"),
            }
        except Exception as e:
            logger.error(f"Error during Reduce phase for {file_path}: {e}")
            raise RuntimeError(f"Reduce phase execution failed: {e}") from e
