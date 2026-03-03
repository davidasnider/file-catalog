from src.core.text_utils import get_all_extracted_text, repair_and_load_json


def test_get_all_extracted_text_aggregation():
    ctx = {
        "TextExtractor": {"text": "Doc text"},
        "DocumentAIExtractor": {"text": "DocAI text"},
        "audio_transcriber": {"text": "Spoken transcript"},
        "vision_analyzer": {"description": "Image description"},
        "video_analyzer": {"visual_description": "Keyframe summary"},
    }
    result = get_all_extracted_text(ctx)

    assert "Doc text" in result
    assert "DocAI text" in result
    assert "[Audio Transcript]\nSpoken transcript" in result
    assert "[Visual Description]\nImage description" in result
    assert "[Video Visual Description]\nKeyframe summary" in result

    # Check ordering (implied by content order in result)
    assert result.index("Doc text") < result.index("DocAI text")
    assert result.index("DocAI text") < result.index("[Audio Transcript]")
    assert result.index("[Audio Transcript]") < result.index("[Visual Description]")
    assert result.index("[Visual Description]") < result.index(
        "[Video Visual Description]"
    )


def test_get_all_extracted_text_partial():
    ctx = {
        "TextExtractor": {"text": "Doc text"},
        "vision_analyzer": {"description": "Image description"},
    }
    result = get_all_extracted_text(ctx)

    assert "Doc text" in result
    assert "Image description" in result
    assert "[Audio Transcript]" not in result
    assert "[Video Visual Description]" not in result


def test_repair_and_load_json_basic():
    text = '{"name": "test", "value": 123}'
    assert repair_and_load_json(text) == {"name": "test", "value": 123}


def test_repair_and_load_json_markdown():
    text = '```json\n{"name": "test"}\n```'
    assert repair_and_load_json(text) == {"name": "test"}


def test_repair_and_load_json_truncated_heuristic():
    text = '{"description": "A beautiful sunset'
    result = repair_and_load_json(text)
    assert result["description"] == "A beautiful sunset"
