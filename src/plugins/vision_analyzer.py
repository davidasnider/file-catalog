import logging
from typing import Dict, Any

from src.core.plugin_registry import AnalyzerBase, register_analyzer
from src.llm.factory import get_llm_provider

logger = logging.getLogger(__name__)


@register_analyzer(name="vision_analyzer", depends_on=[], version="1.0")
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
                "Analyze this image and provide a JSON response. "
                "Include a concise 'description' of the visual contents (do not extract long repetitive text or barcodes), "
                "and strictly set 'is_sfw' to true if it is safe for work, or false if it is Not Safe For Work containing explicit/inappropriate content.\n\n"
                "Desired Output Format (Valid JSON ONLY):\n"
                "{\n"
                '  "description": "A concise description of the image content.",\n'
                '  "is_sfw": true\n'
                "}\n\n"
                "Return ONLY valid JSON. Do not include introductory text or follow-up explanations."
            )

            response_text = await llm.process_image(
                image_path=file_path,
                prompt=prompt,
                max_tokens=512,
                temperature=0.0,  # Zero temperature as recommended for structured JSON
            )

            try:
                from src.core.text_utils import repair_and_load_json

                res_data = repair_and_load_json(response_text)

                return {
                    "description": res_data.get(
                        "description", "No description provided."
                    ),
                    "is_sfw": res_data.get("is_sfw", True),
                    "source": "vision_analyzer",
                }
            except Exception:
                logger.error(
                    f"Failed to parse Vision LLM JSON response for {file_path}. Raw text: {response_text}"
                )
                # Be conservative: treat unparseable responses as not safe for work
                # Avoid returning the raw response_text to prevent polluting downstream text summarizers
                return {
                    "description": "Image analysis completed but the model failed to output a formatted description.",
                    "is_sfw": False,  # Conservative default
                    "source": "vision_analyzer",
                    "parse_error": True,
                }

        except Exception as e:
            logger.error(f"Vision analysis failed for {file_path}: {e}")
            raise Exception(f"Vision analysis failed: {str(e)}")
