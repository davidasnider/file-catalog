import logging
from typing import Dict, Any

from src.core.plugin_registry import AnalyzerBase, register_analyzer

logger = logging.getLogger(__name__)

# ISO 639-1 code to language name mapping for common languages
LANGUAGE_NAMES = {
    "af": "Afrikaans",
    "ar": "Arabic",
    "bg": "Bulgarian",
    "bn": "Bengali",
    "ca": "Catalan",
    "cs": "Czech",
    "cy": "Welsh",
    "da": "Danish",
    "de": "German",
    "el": "Greek",
    "en": "English",
    "es": "Spanish",
    "et": "Estonian",
    "fa": "Persian",
    "fi": "Finnish",
    "fr": "French",
    "gu": "Gujarati",
    "he": "Hebrew",
    "hi": "Hindi",
    "hr": "Croatian",
    "hu": "Hungarian",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "kn": "Kannada",
    "ko": "Korean",
    "lt": "Lithuanian",
    "lv": "Latvian",
    "mk": "Macedonian",
    "ml": "Malayalam",
    "mr": "Marathi",
    "ne": "Nepali",
    "nl": "Dutch",
    "no": "Norwegian",
    "pa": "Punjabi",
    "pl": "Polish",
    "pt": "Portuguese",
    "ro": "Romanian",
    "ru": "Russian",
    "sk": "Slovak",
    "sl": "Slovenian",
    "so": "Somali",
    "sq": "Albanian",
    "sv": "Swedish",
    "sw": "Swahili",
    "ta": "Tamil",
    "te": "Telugu",
    "th": "Thai",
    "tl": "Tagalog",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "ur": "Urdu",
    "vi": "Vietnamese",
    "zh-cn": "Chinese (Simplified)",
    "zh-tw": "Chinese (Traditional)",
}

MIN_TEXT_LENGTH = 20


@register_analyzer(name="LanguageDetector", depends_on=["TextExtractor"], version="1.0")
class LanguageDetectorPlugin(AnalyzerBase):
    """
    Detects the primary language of a document using the langdetect library.
    Stores language code, name, and confidence scores.
    """

    def should_run(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> bool:
        extracted_text = context.get("TextExtractor", {}).get("text", "")
        return len(extracted_text) >= MIN_TEXT_LENGTH

    async def analyze(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info(f"Detecting language for {file_path}")

        from langdetect import detect, detect_langs, LangDetectException

        extracted_text = context.get("TextExtractor", {}).get("text", "")

        try:
            language_code = detect(extracted_text)
            language_probs = detect_langs(extracted_text)

            all_languages = [
                {"code": str(lang.lang), "probability": round(lang.prob, 4)}
                for lang in language_probs
            ]

            confidence = round(language_probs[0].prob, 4) if language_probs else 0.0
            language_name = LANGUAGE_NAMES.get(language_code, language_code)

            return {
                "language": language_code,
                "language_name": language_name,
                "confidence": confidence,
                "all_languages": all_languages,
                "source": "language_detector",
            }

        except LangDetectException as e:
            logger.warning(f"Language detection failed for {file_path}: {e}")
            return {
                "language": "unknown",
                "language_name": "Unknown",
                "confidence": 0.0,
                "all_languages": [],
                "source": "language_detector",
                "error": str(e),
            }
