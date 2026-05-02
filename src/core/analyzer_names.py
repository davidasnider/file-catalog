"""
Centralized repository for all analyzer plugin names.
Used to avoid hardcoded strings and cross-plugin import dependencies.
"""

TEXT_EXTRACTOR_NAME = "TextExtractor"
DOCUMENT_AI_EXTRACTOR_NAME = "DocumentAIExtractor"
AUDIO_TRANSCRIBER_NAME = "AudioTranscriber"
VIDEO_ANALYZER_NAME = "VideoAnalyzer"
VISION_ANALYZER_NAME = "VisionAnalyzer"
ROUTER_NAME = "Router"
SUMMARIZER_NAME = "Summarizer"
DEEP_SUMMARIZER_NAME = "DeepSummarizer"
ESTATE_ANALYZER_NAME = "EstateAnalyzer"
PII_HARVESTER_NAME = "PIIHarvester"
PASSWORD_EXTRACTOR_NAME = "PasswordExtractor"  # pragma: allowlist secret
LANGUAGE_DETECTOR_NAME = "LanguageDetector"
METADATA_EXTRACTOR_NAME = "MetadataExtractor"
SPREADSHEET_ANALYZER_NAME = "SpreadsheetAnalyzer"
EMAIL_PARSER_NAME = "EmailParser"
DUPLICATE_DETECTOR_NAME = "DuplicateDetector"
OCR_CONFIDENCE_SCORER_NAME = "OCRConfidenceScorer"
