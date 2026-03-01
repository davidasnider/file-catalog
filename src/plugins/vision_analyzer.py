import logging
from typing import Dict, Any
import json
import os

from src.core.plugin_registry import AnalyzerBase, register_analyzer
from src.llm.llama_cpp import get_llm_provider

logger = logging.getLogger(__name__)

# We use the Llava-1.5-7b model which we added to KNOWN_MODELS
VISION_MODEL_PATH = "models/Llava-1.5-7b-ggml-model-q4_k.gguf"


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
            # We must ensure the model path exists or will be downloaded
            abs_model_path = os.path.join(os.getcwd(), VISION_MODEL_PATH)

            # The get_provider call handles downloading if we mapped it in KNOWN_MODELS correctly
            llm = get_llm_provider(abs_model_path)

            if isinstance(llm, str):
                raise Exception(f"Failed to load vision LLM: {llm}")

            prompt = (
                "Analyze this image and provide a JSON response. "
                "Include a detailed 'description' of the visual contents, "
                "and strictly set 'is_sfw' to true if it is safe for work, or false if it is Not Safe For Work containing explicit/inappropriate content. "
                "Return ONLY valid JSON."
            )

            response_text = await llm.process_image(
                image_path=file_path,
                prompt=prompt,
                max_tokens=512,
                temperature=0.2,  # low temp for JSON stability
            )

            # Strip out markdown formatting if the model wrapped it
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]

            response_text = response_text.strip()

            try:
                # Handle cases where the LLM might escape underscores (e.g., is\_sfw)
                cleaned_response = response_text.replace("\\_", "_").strip()
                # Find start and end of JSON if LLM included other text
                start = cleaned_response.find("{")
                end = cleaned_response.rfind("}") + 1
                if start != -1 and end > start:
                    cleaned_response = cleaned_response[start:end]

                res_data = json.loads(cleaned_response)
                return {
                    "description": res_data.get(
                        "description", "No description provided."
                    ),
                    "is_sfw": res_data.get("is_sfw", True),
                    "source": "vision_analyzer",
                }
            except Exception:  # Removed 'as e' as 'e' was unused here
                logger.error(
                    f"Failed to parse Vision LLM JSON response for {file_path}. Raw: {response_text}"
                )
                # Fallback if the model failed to output strict JSON
                return {
                    "description": response_text,
                    "is_sfw": True,  # Assume safe if we can't parse it
                    "source": "vision_analyzer",
                    "parse_error": True,
                }

        except Exception as e:
            logger.error(f"Vision analysis failed for {file_path}: {e}")
            raise Exception(f"Vision analysis failed: {str(e)}")
