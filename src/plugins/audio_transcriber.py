import logging
from typing import Dict, Any
import asyncio
from faster_whisper import WhisperModel

from src.core.plugin_registry import AnalyzerBase, register_analyzer
from src.core.analyzer_names import TEXT_EXTRACTOR_NAME, AUDIO_TRANSCRIBER_NAME

logger = logging.getLogger(__name__)

# Fallback on "base" model for speed on standard hardware
MODEL_SIZE = "base"
model = None
_model_lock = None


def get_model_lock():
    global _model_lock
    if _model_lock is None:
        _model_lock = asyncio.Lock()
    return _model_lock


async def get_whisper_model():
    global model
    async with get_model_lock():
        if model is None:
            logger.info(f"Loading faster-whisper model ({MODEL_SIZE})...")
            # auto chooses GPU or CPU
            model = WhisperModel(MODEL_SIZE, device="auto", compute_type="default")
        return model


@register_analyzer(name=AUDIO_TRANSCRIBER_NAME, depends_on=[], version="1.0")
class AudioTranscriberPlugin(AnalyzerBase):
    """
    Extracts audio transcripts from audio and video files using faster-whisper.
    """

    def should_run(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> bool:
        # Avoid running if we somehow already have text (though we shouldn't unless cached)
        if "text" in context.get(TEXT_EXTRACTOR_NAME, {}):
            return False

        return mime_type.startswith("audio/") or mime_type.startswith("video/")

    async def analyze(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info(f"Transcribing audio/video for {file_path}")

        try:
            # We run the transcription in a thread pool since Whisper is CPU/GPU bound and blocking
            loop = asyncio.get_running_loop()
            # Get model before entering executor as it is async
            whisper = await get_whisper_model()

            def transcribe():
                try:
                    segments, info = whisper.transcribe(file_path, beam_size=5)
                    # Ensure generator is exhausted to get all text
                    transcript = " ".join([segment.text for segment in segments])
                    return transcript, getattr(info, "language", "unknown")
                except Exception as inner_e:
                    logger.warning(f"Whisper inner transcription error: {inner_e}")
                    return "", "unknown"

            transcript, language = await loop.run_in_executor(None, transcribe)

            # We inject the transcript into the context as if it were extracted text,
            # so downstream summarizers can use it identically.
            return {
                "text": transcript.strip(),
                "extracted": bool(transcript.strip()),
                "language": language,
                "source": AUDIO_TRANSCRIBER_NAME,
            }

        except Exception as e:
            logger.error(f"Failed to transcribe {file_path}: {e}")
            raise Exception(f"Audio transcription failed: {str(e)}")
