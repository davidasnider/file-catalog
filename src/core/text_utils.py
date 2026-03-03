from typing import Dict, Any


def get_all_extracted_text(context: Dict[str, Any]) -> str:
    """
    Aggregates text extracted from all available analyzers in the context.
    This ensures that summaries and routing can use audio transcripts,
    video visual descriptions, and image descriptions in addition to standard text.
    """
    aggregated_parts = []

    # 1. Standard Document / OCR Text Extractor
    if "TextExtractor" in context:
        text = context["TextExtractor"].get("text", "").strip()
        if text:
            aggregated_parts.append(text)

    # 2. Document AI (replaces TextExtractor when enabled)
    if "DocumentAIExtractor" in context:
        docai_text = context["DocumentAIExtractor"].get("text", "").strip()
        if docai_text:
            aggregated_parts.append(docai_text)

    # 3. Audio Transcriber
    if "audio_transcriber" in context:
        transcript = context["audio_transcriber"].get("text", "").strip()
        if transcript:
            aggregated_parts.append(f"[Audio Transcript]\n{transcript}")

    # 4. Vision Analyzer (Image Descriptions)
    if "vision_analyzer" in context:
        img_desc = context["vision_analyzer"].get("description", "").strip()
        if img_desc:
            aggregated_parts.append(f"[Visual Description]\n{img_desc}")

    # 5. Video Analyzer (Keyframe Descriptions)
    if "video_analyzer" in context:
        vid_desc = context["video_analyzer"].get("visual_description", "").strip()
        if vid_desc:
            aggregated_parts.append(f"[Video Visual Description]\n{vid_desc}")

    return "\n\n".join(aggregated_parts)


def repair_and_load_json(text: str) -> Dict[str, Any]:
    """
    Attempts to extract, repair, and parse JSON from a string.
    Useful for handling non-compliant LLM outputs.
    """
    import json
    import re
    from json_repair import repair_json

    # 1. Basic cleanup
    cleaned = text.strip()
    # Remove common markdown escapes that break JSON
    cleaned = cleaned.replace("\\_", "_").replace("\\*", "*")

    # 2. Extract JSON block if surrounded by text
    match = re.search(r"(\{.*\})", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(1)

    # 3. Use json-repair to fix common issues
    repaired = repair_json(cleaned)

    # 4. Parse
    try:
        data = json.loads(repaired)
        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        # 5. LAST RESORT HEURISTIC for severely truncated LLM JSON
        # e.g. {"description": "A woman standing... [TRUNCATED]
        data = {}
        # Try to extract anything that looks like "description": "..."
        desc_match = re.search(
            r'"description":\s*"(.*?)(?:"|$)', cleaned, re.IGNORECASE | re.DOTALL
        )
        if desc_match:
            data["description"] = desc_match.group(1).strip()

        # Try to extract score: "score": 5
        score_match = re.search(
            r'"(?:adult_content_)?score":\s*(\d+(?:\.\d+)?)', cleaned, re.IGNORECASE
        )
        if score_match:
            data["adult_content_score"] = float(score_match.group(1))

        # Try to extract is_sfw: "is_sfw": true
        sfw_match = re.search(r'"is_sfw":\s*(true|false)', cleaned, re.IGNORECASE)
        if sfw_match:
            data["is_sfw"] = sfw_match.group(1).lower() == "true"

        return data
