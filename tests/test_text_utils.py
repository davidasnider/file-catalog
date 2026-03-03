from src.core.text_utils import get_all_extracted_text


def test_get_all_extracted_text_standard():
    context = {"TextExtractor": {"text": "Standard text extractor content."}}
    result = get_all_extracted_text(context)
    assert result == "Standard text extractor content."


def test_get_all_extracted_text_multiple():
    context = {
        "TextExtractor": {"text": "Standard OCR text."},
        "audio_transcriber": {"text": "This is an audio transcript."},
        "vision_analyzer": {"description": "A picture of a cat."},
    }
    result = get_all_extracted_text(context)
    assert "Standard OCR text." in result
    assert "[Audio Transcript]\nThis is an audio transcript." in result
    assert "[Visual Description]\nA picture of a cat." in result
    assert "\n\n" in result


def test_get_all_extracted_text_empty():
    context = {}
    result = get_all_extracted_text(context)
    assert result == ""


def test_get_all_extracted_text_document_ai():
    context = {"DocumentAIExtractor": {"text": "Document AI content."}}
    result = get_all_extracted_text(context)
    assert result == "Document AI content."


def test_get_all_extracted_text_video():
    context = {"video_analyzer": {"visual_description": "Video shows a sunset."}}
    result = get_all_extracted_text(context)
    assert "[Video Visual Description]\nVideo shows a sunset." in result
