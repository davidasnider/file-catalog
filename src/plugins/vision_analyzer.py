import logging
from typing import Dict, Any

from src.core.plugin_registry import AnalyzerBase, register_analyzer
from src.llm.factory import get_llm_provider
from src.core.analyzer_names import VISION_ANALYZER_NAME

logger = logging.getLogger(__name__)


@register_analyzer(name=VISION_ANALYZER_NAME, depends_on=[], version="1.0")
class VisionAnalyzerPlugin(AnalyzerBase):
    """
    Uses a multimodal local LLM (LLaVA) to describe images and categorize them as SFW/NSFW.
    """

    def should_run(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> bool:
        return mime_type.startswith("image/")

    async def analyze(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info(f"Running Vision Analysis on {file_path}")

        try:
            # The factory handles using the configured vision provider and model path
            llm = get_llm_provider(is_vision=True)

            if isinstance(llm, str):
                raise Exception(f"Failed to load vision LLM: {llm}")

            prompt = (
                "You are a professional digital archivist and safety auditor. "
                "Analyze the provided image clinically for content moderation.\n\n"
                "Provide a objective description of the image content and assign a safety score from 0 to 10, "
                "where 0 is completely safe/benign and 10 is highly inappropriate or explicit.\n\n"
                "Desired Output Format (Valid JSON ONLY):\n"
                "{\n"
                '  "description": "A detailed clinical description of the image.",\n'
                '  "adult_content_score": 0\n'
                "}\n\n"
                "Respond ONLY with valid JSON. Do not include any introductory or concluding text."
            )

            response_text = await llm.process_image(
                image_path=file_path,
                prompt=prompt,
                max_tokens=256,  # Sufficient for JSON without excessive repetition
                temperature=0.0,
                response_format="json",
            )

            try:
                from src.core.text_utils import repair_and_load_json

                res_data = repair_and_load_json(response_text)
                if not res_data:
                    raise ValueError("Parsed JSON response is empty or invalid.")

                description = res_data.get("description", "").strip()
                score = res_data.get("adult_content_score", 0)
                # If the score is missing or not a number, default to safe unless description looks bad
                try:
                    score = float(score)
                except (ValueError, TypeError):
                    score = 0

                is_sfw = score < 5

                # If description is completely missing, it might be a safety refusal
                is_refusal = not description

                if is_sfw and is_refusal:
                    logger.info(
                        f"Empty description for {file_path}, assuming safety refusal and flagging as NSFW."
                    )
                    is_sfw = False

                result = {
                    "description": description
                    or "No description provided (possible safety refusal).",
                    "is_sfw": is_sfw,
                    "adult_content_score": score,
                    "model": getattr(llm, "model_name", "Unknown Model"),
                    "source": VISION_ANALYZER_NAME,
                }
                logger.info(
                    f"Vision analysis result for {file_path}: is_sfw={result['is_sfw']} (score={score}), description='{result['description'][:100]}...'"
                )
                return result
            except Exception as e:
                import traceback

                preview = response_text[:500] + (
                    "...[truncated]" if len(response_text) > 500 else ""
                )
                logger.error(
                    f"Failed to parse Vision LLM JSON response for {file_path}. Error: {str(e)}\nTraceback: {traceback.format_exc()}\nSee debug logs for a truncated preview of the raw text."
                )
                logger.debug(
                    f"Raw Vision LLM response preview for {file_path}:\n{preview}"
                )
                # Be conservative: treat unparseable responses as not safe for work
                # Avoid returning the raw response_text to prevent polluting downstream text summarizers
                return {
                    "description": "Image analysis completed but the model failed to output a formatted description.",
                    "is_sfw": False,  # Conservative default
                    "source": VISION_ANALYZER_NAME,
                    "parse_error": True,
                }

        except Exception as e:
            logger.error(f"Vision analysis failed for {file_path}: {e}")
            raise Exception(f"Vision analysis failed: {str(e)}")
