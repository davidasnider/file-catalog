import logging
from typing import Dict, Any
import json

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
                "and strictly set 'is_sfw' to true if it is safe for work, or false if it is Not Safe For Work containing explicit/inappropriate content. "
                'Return ONLY valid JSON in the following format exactly: {"description": "...", "is_sfw": true}'
            )

            response_text = await llm.process_image(
                image_path=file_path,
                prompt=prompt,
                max_tokens=512,
                temperature=0.2,  # low temp for JSON stability
            )

            try:
                # Robust JSON extraction using regex and finding boundaries
                import re

                # 1. Preliminary cleanup: remove common markdown escapes
                cleaned = response_text.replace("\\_", "_").replace("\\*", "*").strip()

                # 2. Try to find JSON block using regex or bracket counting
                # This regex looks for anything between { and } including nested braces
                match = re.search(r"(\{.*\})", cleaned, re.DOTALL)
                if match:
                    cleaned_json = match.group(1)
                else:
                    # Fallback to finding first/last brace if regex failed
                    start = cleaned.find("{")
                    end = cleaned.rfind("}") + 1
                    if start != -1 and end > start:
                        cleaned_json = cleaned[start:end]
                    else:
                        cleaned_json = cleaned

                try:
                    res_data = json.loads(cleaned_json)
                except json.JSONDecodeError:
                    # HEURISTIC PARSING for "Lazy JSON" or truncated responses
                    # e.g. {"description": A fish... (no quotes, no end brace)
                    logger.warning(
                        f"JSON decode failed for {file_path}, attempting heuristic extraction."
                    )
                    res_data = {}

                    # Extract description: look for "description": followed by text until end or "is_sfw"
                    # Handles both quoted and unquoted values
                    desc_match = re.search(
                        r'"description":\s*"?([^"]*)"?,?', cleaned_json, re.IGNORECASE
                    )
                    if not desc_match:
                        # try even more liberal matching if quotes are missing entirely
                        desc_match = re.search(
                            r'"description":\s*(.*?)(?:,\s*"is_sfw"|\s*\})',
                            cleaned_json,
                            re.IGNORECASE | re.DOTALL,
                        )

                    if desc_match:
                        res_data["description"] = desc_match.group(1).strip()
                    else:
                        # Final fallback: use the whole string if it looks like a description
                        if len(cleaned_json) > 10:
                            res_data["description"] = (
                                cleaned_json.replace('{"description":', "")
                                .replace("}", "")
                                .strip()
                            )

                    # Extract is_sfw: look for true/false
                    sfw_match = re.search(
                        r'"is_sfw":\s*(true|false)', cleaned_json, re.IGNORECASE
                    )
                    if sfw_match:
                        res_data["is_sfw"] = sfw_match.group(1).lower() == "true"

                return {
                    "description": res_data.get(
                        "description", "No description provided."
                    ),
                    "is_sfw": res_data.get("is_sfw", True),
                    "source": "vision_analyzer",
                }
            except Exception:
                logger.error(
                    f"Failed to parse Vision LLM JSON response for {file_path}."
                )
                logger.debug(f"Raw unparseable text: {response_text}")
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
