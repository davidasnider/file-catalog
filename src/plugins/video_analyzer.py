import logging
from typing import Dict, Any
import json
import os
import tempfile

from src.core.plugin_registry import AnalyzerBase, register_analyzer
from src.llm.factory import get_llm_provider
from src.core.analyzer_names import VIDEO_ANALYZER_NAME, AUDIO_TRANSCRIBER_NAME

# Conditional import as PyAV might not be installed yet during tests
try:
    import av

    HAS_AV = True
except ImportError:
    HAS_AV = False

logger = logging.getLogger(__name__)


@register_analyzer(
    name=VIDEO_ANALYZER_NAME, depends_on=[AUDIO_TRANSCRIBER_NAME], version="1.0"
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
        """Extracts a single frame from roughly the middle of the video using PyAV and saves it to a temp file."""
        if not HAS_AV:
            raise ImportError("PyAV (av library) is not installed.")

        try:
            container = av.open(file_path)
            # Find the first video stream
            video_stream = next(s for s in container.streams if s.type == "video")

            # Seek to roughly the middle of the video
            if video_stream.duration is not None:
                target_ts = int(video_stream.duration / 2)
                container.seek(target_ts, stream=video_stream)

            # Grab the first decoded frame after seeking
            for frame in container.decode(video_stream):
                img = frame.to_image()  # Converts to PIL Image
                fd, temp_path = tempfile.mkstemp(suffix=".jpg")
                os.close(fd)
                img.save(temp_path, format="JPEG")
                container.close()
                return temp_path

            container.close()
            raise Exception("No video frames could be decoded.")

        except Exception as e:
            raise Exception(f"Failed to extract frame using PyAV: {str(e)}")

    async def analyze(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info(f"Running Video Analysis on {file_path}")

        temp_img_path = None
        try:
            # 1. Grab transcript from our dependency plugin if it successfully ran
            transcript = context.get(AUDIO_TRANSCRIBER_NAME, {}).get("text", "")

            # 2. Extract Keyframe
            temp_img_path = self.extract_keyframe(file_path)

            # 3. Process the frame with Vision LLM
            llm = get_llm_provider(is_vision=True)

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
