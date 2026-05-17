import logging
from typing import Dict, Any

from src.core.plugin_registry import AnalyzerBase, register_analyzer
from src.llm.factory import get_llm_provider
from src.core.analyzer_names import (
    TEXT_EXTRACTOR_NAME,
    DEEP_SUMMARIZER_NAME,
    ROUTER_NAME,
    SUMMARIZER_NAME,
    EMAIL_PARSER_NAME,
)

logger = logging.getLogger(__name__)

# Reusing the configured LLM model for Map-Reduce summarization


@register_analyzer(
    name=DEEP_SUMMARIZER_NAME,
    depends_on=[
        TEXT_EXTRACTOR_NAME,
        ROUTER_NAME,
        SUMMARIZER_NAME,
        EMAIL_PARSER_NAME,
    ],
    version="1.3",
)
class DeepSummarizerPlugin(AnalyzerBase):
    """
    Performs Map-Reduce extensive summarization on large documents exceeding the standard context window.
    """

    def should_run(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> bool:
        from src.core.text_utils import get_all_extracted_text

        extracted_text = get_all_extracted_text(context)
        # Only trigger Deep Summarization for large texts (> 20,000 characters)
        if len(extracted_text) < 20000:
            return False

        router_data = context.get(ROUTER_NAME, {})
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

        from src.core.text_utils import get_all_extracted_text

        extracted_text = get_all_extracted_text(context)

        # We pass n_ctx just in case the factory/manager respects it
        llm = get_llm_provider(is_vision=False, n_ctx=8192)
        if not llm:
            return {
                "extensive_summary": "",
                "skipped": True,
                "error": "LLM Provider uninitialized",
            }
        elif isinstance(llm, str):
            from src.core.config import config

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
                "extensive_summary": "",
                "skipped": True,
                "error": error_msg,
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

            CRITICAL INSTRUCTION: Output ONLY the summary.
            DO NOT output any thinking process. NO <think> tags. NO "Here is a thinking process".
            Do NOT include any conversational filler or preambles.

            TEXT CHUNK {i + 1}/{len(chunks)}:
            {chunk}

            SUMMARY:
            """
            try:
                safe_tokens = await llm.get_safe_output_tokens(prompt)
                response = await llm.generate(
                    prompt, max_tokens=safe_tokens, temperature=0.2
                )
                chunk_summaries.append(self._strip_thinking(response))
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

        CRITICAL INSTRUCTION: Output ONLY the summary.
        DO NOT output any thinking process. NO <think> tags. NO "Here is a thinking process".
        Do NOT include any conversational filler or preambles.

        DOCUMENT PARTS:
        {combined_summaries}

        FINAL EXTENSIVE SUMMARY:
        """

        try:
            safe_tokens = await llm.get_safe_output_tokens(final_prompt)
            final_response = await llm.generate(
                final_prompt, max_tokens=safe_tokens, temperature=0.3
            )
            cleaned_final = self._strip_thinking(final_response)
            return {
                "extensive_summary": cleaned_final,
                "summary": cleaned_final,  # duplicate for UI backward compatibility
                "skipped": False,
                "chunks_processed": len(chunk_summaries),
                "model": getattr(llm, "model_name", "Unknown Deep Model"),
            }
        except Exception as e:
            logger.error(f"Error during Reduce phase for {file_path}: {e}")
            raise RuntimeError(f"Reduce phase execution failed: {e}") from e
