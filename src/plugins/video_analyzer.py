import logging
from typing import Dict, Any
import json
import os
import tempfile

from src.core.plugin_registry import AnalyzerBase, register_analyzer
from src.llm.llama_cpp import get_llm_provider

# Conditional import as opencv-python-headless might not be installed yet during tests
try:
    import cv2

    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

logger = logging.getLogger(__name__)

VISION_MODEL_PATH = "models/Llava-1.5-7b-ggml-model-q4_k.gguf"


@register_analyzer(
    name="video_analyzer", depends_on=["audio_transcriber"], version="1.0"
)
class VideoAnalyzerPlugin(AnalyzerBase):
    """
    Extracts keyframes from videos and uses a multimodal LLM to describe visual content.
    Combines with the audio transcript if available.
    """

    def should_run(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> bool:
        return mime_type.startswith("video/")

    def extract_keyframe(self, file_path: str) -> str:
        """Extracts a single frame from the middle of the video and saves it to a temp file."""
        if not HAS_CV2:
            raise ImportError("opencv-python-headless is not installed.")

        vidcap = cv2.VideoCapture(file_path)
        if not vidcap or not vidcap.isOpened():
            raise Exception(
                f"Failed to open video file for frame extraction: {file_path}"
            )

        total_frames = int(vidcap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            raise Exception("Video has no frames.")

        # Get a frame from roughly the middle to avoid blank title screens
        vidcap.set(cv2.CAP_PROP_POS_FRAMES, total_frames // 2)
        success, image = vidcap.read()
        vidcap.release()

        if not success:
            raise Exception("Could not read frame from video.")

        # Save to temp file using mkstemp to avoid handle leaks
        fd, temp_path = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        if not cv2.imwrite(temp_path, image):
            raise Exception(
                f"Failed to write extracted frame to temporary file: {temp_path}"
            )
        return temp_path

    async def analyze(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info(f"Running Video Analysis on {file_path}")

        temp_img_path = None
        try:
            # 1. Grab transcript from our dependency plugin if it successfully ran
            transcript = context.get("audio_transcriber", {}).get("text", "")

            # 2. Extract Keyframe
            temp_img_path = self.extract_keyframe(file_path)

            # 3. Process the frame with Vision LLM
            abs_model_path = os.path.join(os.getcwd(), VISION_MODEL_PATH)
            llm = get_llm_provider(abs_model_path)

            if isinstance(llm, str):
                raise Exception(f"Failed to load vision LLM: {llm}")

            prompt = (
                "Analyze this keyframe from a video and provide a JSON response. "
                "Include a detailed 'description' of the visual contents. "
                "Return ONLY valid JSON."
            )

            if transcript:
                prompt += f"\n\nContext from audio transcript: {transcript}"

            response_text = await llm.process_image(
                image_path=temp_img_path, prompt=prompt, max_tokens=512, temperature=0.2
            )

            # Strip markdown formatting
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]

            response_text = response_text.strip()

            try:
                result = json.loads(response_text)
                return {
                    "visual_description": result.get(
                        "description", "No visual description provided."
                    ),
                    "source": "video_analyzer",
                }
            except json.JSONDecodeError:
                logger.error(
                    f"Failed to parse Vision LLM JSON response for Video {file_path}. Raw: {response_text}"
                )
                return {
                    "visual_description": response_text,
                    "source": "video_analyzer",
                    "parse_error": True,
                }

        except Exception as e:
            logger.error(f"Video analysis failed for {file_path}: {e}")
            raise Exception(f"Video analysis failed: {str(e)}")
        finally:
            if temp_img_path and os.path.exists(temp_img_path):
                os.remove(temp_img_path)
