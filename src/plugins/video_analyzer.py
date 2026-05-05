import logging
from typing import Dict, Any
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
    name=VIDEO_ANALYZER_NAME, depends_on=[AUDIO_TRANSCRIBER_NAME], version="2.0"
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

    def extract_keyframes(self, file_path: str, count: int = 100) -> list[str]:
        """Extracts N frames from across the video using PyAV and saves them to temp files."""
        if not HAS_AV:
            raise ImportError("PyAV (av library) is not installed.")

        temp_paths = []
        consecutive_failures = 0
        max_consecutive_failures = 5

        try:
            container = av.open(file_path)
            # Find the first video stream
            try:
                video_stream = next(s for s in container.streams if s.type == "video")
            except StopIteration:
                container.close()
                logger.warning(f"No video stream found in {file_path}")
                return []

            duration = video_stream.duration
            if duration is None:
                # Fallback to container duration if stream duration is missing
                duration = container.duration

            if duration:
                # Calculate timestamps for uniform sampling
                start_offset = duration * 0.05
                end_offset = duration * 0.95
                usable_duration = end_offset - start_offset

                interval = usable_duration / max(1, count - 1)
                timestamps = [int(start_offset + i * interval) for i in range(count)]

                for ts in timestamps:
                    try:
                        container.seek(ts, stream=video_stream)
                        # Decode the next available frame
                        for frame in container.decode(video_stream):
                            img = frame.to_image()
                            fd, temp_path = tempfile.mkstemp(suffix=".jpg")
                            os.close(fd)
                            img.save(temp_path, format="JPEG")
                            temp_paths.append(temp_path)
                            consecutive_failures = 0
                            break
                    except PermissionError as pe:
                        logger.error(f"Permission denied accessing {file_path}: {pe}")
                        break  # Abort entire file
                    except Exception as e:
                        consecutive_failures += 1
                        logger.warning(
                            f"Failed to extract frame at timestamp {ts} for {file_path}: {e}"
                        )
                        if consecutive_failures >= max_consecutive_failures:
                            logger.error(
                                f"Aborting frame extraction for {file_path} after {consecutive_failures} failures."
                            )
                            break
                        continue
            else:
                # Fallback to a single frame if duration is unknown
                try:
                    for frame in container.decode(video_stream):
                        img = frame.to_image()
                        fd, temp_path = tempfile.mkstemp(suffix=".jpg")
                        os.close(fd)
                        img.save(temp_path, format="JPEG")
                        temp_paths.append(temp_path)
                        break
                except PermissionError as pe:
                    logger.error(f"Permission denied accessing {file_path}: {pe}")
                except Exception as e:
                    logger.warning(
                        f"Failed to extract single frame for {file_path}: {e}"
                    )

            container.close()
            if not temp_paths:
                raise Exception("No video frames could be decoded.")
            return temp_paths

        except Exception as e:
            # Cleanup any frames already extracted before re-raising
            for p in temp_paths:
                if os.path.exists(p):
                    os.remove(p)
            raise Exception(f"Failed to extract frames using PyAV: {str(e)}")

    async def analyze(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info(f"Running Video Analysis on {file_path}")

        temp_img_paths = []
        try:
            # 1. Grab transcript from our dependency plugin if it successfully ran
            transcript = context.get(AUDIO_TRANSCRIBER_NAME, {}).get("text", "")

            # 2. Extract Keyframes (100 as requested)
            temp_img_paths = self.extract_keyframes(file_path, count=100)

            if not temp_img_paths:
                logger.info(
                    f"Skipping video visual analysis for {file_path}: No keyframes available."
                )
                return {
                    "visual_description": "No video content found (possible audio-only file).",
                    "skipped": True,
                    "reason": "no_video_stream",
                    "source": VIDEO_ANALYZER_NAME,
                }

            # 3. Process the frames with Vision LLM in batches
            # Processing 100 images at once exceeds the context window of most local models.
            # We use a batch size of 20 to balance detail and token limits.
            llm = get_llm_provider(is_vision=True)
            if isinstance(llm, str):
                raise Exception(f"Failed to load vision LLM: {llm}")

            batch_size = 20
            partial_descriptions = []

            for i in range(0, len(temp_img_paths), batch_size):
                batch = temp_img_paths[i : i + batch_size]
                batch_num = (i // batch_size) + 1
                total_batches = (len(temp_img_paths) + batch_size - 1) // batch_size

                logger.info(
                    f"Processing video batch {batch_num}/{total_batches} for {file_path}"
                )

                batch_prompt = (
                    f"Analyze these {len(batch)} keyframes from a video segment. "
                    "Describe the visual content, actions, and any notable changes in this specific segment. "
                    "Return ONLY a concise paragraph description."
                )

                # We don't use JSON mode here to keep descriptions dense and avoid schema overhead
                try:
                    desc = await llm.process_image(
                        image_path=batch,
                        prompt=batch_prompt,
                        max_tokens=300,
                        temperature=0.2,
                    )
                    partial_descriptions.append(f"Segment {batch_num}: {desc.strip()}")
                except Exception as e:
                    logger.warning(
                        f"Failed to process video batch {batch_num} for {file_path}: {e}"
                    )

            if not partial_descriptions:
                raise Exception(
                    "Failed to generate any partial descriptions for the video."
                )

            # 4. Synthesize partial descriptions into a final JSON response
            # We use the text-only LLM for synthesis to save VRAM and handle the aggregated text
            text_llm = get_llm_provider(is_vision=False)
            if isinstance(text_llm, str):
                text_llm = llm  # Fallback to vision model if text model is same

            combined_segments = "\n\n".join(partial_descriptions)

            final_prompt = (
                "You are finalizing a video analysis task. Below are descriptions of sequential segments of a video. "
                "Synthesize these into a single, cohesive, detailed description of the entire video's contents. "
                "Highlight key events, characters, objects, and any overarching narrative or theme. "
                "Desired Output Format (Valid JSON ONLY):\n"
                "{\n"
                '  "description": "The final cohesive description..."\n'
                "}\n\n"
            )

            if transcript:
                final_prompt += f"Context from audio transcript: {transcript}\n\n"

            final_prompt += f"SEGMENT DESCRIPTIONS:\n{combined_segments}"

            response_text = await text_llm.generate(
                final_prompt, max_tokens=1024, temperature=0.3, response_format="json"
            )

            try:
                from src.core.text_utils import repair_and_load_json

                result = repair_and_load_json(response_text)

                if not result or "description" not in result:
                    return {
                        "visual_description": response_text,
                        "source": VIDEO_ANALYZER_NAME,
                        "parse_error": True,
                    }

                return {
                    "visual_description": result["description"],
                    "model": getattr(llm, "model_name", "Unknown Model"),
                    "source": VIDEO_ANALYZER_NAME,
                }
            except Exception:
                logger.error(
                    f"Failed to parse synthesis response for {file_path}. Raw: {response_text}"
                )
                return {
                    "visual_description": response_text,
                    "source": VIDEO_ANALYZER_NAME,
                    "parse_error": True,
                }

        except Exception as e:
            logger.error(f"Video analysis failed for {file_path}: {e}")
            raise Exception(f"Video analysis failed: {str(e)}")
        finally:
            for p in temp_img_paths:
                if os.path.exists(p):
                    os.remove(p)
