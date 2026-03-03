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
