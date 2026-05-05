import argparse
import asyncio
import json
import logging
import random
from typing import List, Dict, Any

from sqlalchemy import select, and_
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.engine import async_session_maker
from src.db.models import Document, AnalysisTask, TaskStatus
from src.llm.factory import get_llm_provider
from src.core.text_utils import get_all_extracted_text, repair_and_load_json
from src.core.analyzer_names import (
    SUMMARIZER_NAME,
    DEEP_SUMMARIZER_NAME,
    TEXT_EXTRACTOR_NAME,
    VISION_ANALYZER_NAME,
    AUDIO_TRANSCRIBER_NAME,
    VIDEO_ANALYZER_NAME,
    DOCUMENT_AI_EXTRACTOR_NAME,
)

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

JUDGE_PROMPT = """
You are an expert quality assurance agent evaluating the accuracy of document summaries.
Compare the SOURCE TEXT with the GENERATED SUMMARY provided below.

SOURCE TEXT:
{source_text}

GENERATED SUMMARY:
{summary}

EVALUATION CRITERIA:
1. Accuracy (1-5): Does the summary correctly represent the facts in the source text?
2. Coverage (1-5): Does the summary capture the most important points?
3. Hallucination (1-5): 1 means high hallucinations, 5 means no hallucinations detected.

Return your evaluation in the following JSON format:
{{
    "accuracy": 1-5,
    "coverage": 1-5,
    "hallucination_free": 1-5,
    "reasoning": "A brief explanation of your scores"
}}
"""


def normalize_task_name(name: str) -> str:
    """Map legacy snake_case names to current PascalCase constants."""
    mapping = {
        "text_extractor": TEXT_EXTRACTOR_NAME,
        "vision_analyzer": VISION_ANALYZER_NAME,
        "audio_transcriber": AUDIO_TRANSCRIBER_NAME,
        "video_analyzer": VIDEO_ANALYZER_NAME,
        "summarizer": SUMMARIZER_NAME,
        "deep_summarizer": DEEP_SUMMARIZER_NAME,
        "document_ai_extractor": DOCUMENT_AI_EXTRACTOR_NAME,
    }
    return mapping.get(name.lower(), name)


def build_context_from_tasks(tasks: List[AnalysisTask]) -> Dict[str, Any]:
    """Reconstruct a partial plugin context from database tasks."""
    context = {}
    for task in tasks:
        if task.status == TaskStatus.COMPLETED and task.result_data:
            try:
                normalized_name = normalize_task_name(task.task_name)
                context[normalized_name] = json.loads(task.result_data)
            except json.JSONDecodeError:
                continue
    return context


async def get_summary_pairs(session: AsyncSession, limit: int) -> List[Dict[str, Any]]:
    """Fetch random pairs of (extracted_text, summary) from the database."""
    logger.info("Querying database for completed summaries...")

    # Include legacy names in the search
    summary_task_names = [
        SUMMARIZER_NAME,
        DEEP_SUMMARIZER_NAME,
        "summarizer",
        "deep_summarizer",
    ]

    summary_stmt = (
        select(AnalysisTask.document_id)
        .where(
            and_(
                AnalysisTask.task_name.in_(summary_task_names),
                AnalysisTask.status == TaskStatus.COMPLETED,
            )
        )
        .distinct()
    )

    result = await session.execute(summary_stmt)
    doc_ids = result.scalars().all()

    logger.info(f"Found {len(doc_ids)} documents with completed summaries.")

    if not doc_ids:
        return []

    sampled_ids = random.sample(doc_ids, min(len(doc_ids), limit))

    pairs = []
    for doc_id in sampled_ids:
        doc_stmt = select(Document).where(Document.id == doc_id)
        doc_res = await session.execute(doc_stmt)
        doc = doc_res.scalar_one_or_none()

        if not doc:
            continue

        task_stmt = select(AnalysisTask).where(AnalysisTask.document_id == doc_id)
        task_result = await session.execute(task_stmt)
        tasks = task_result.scalars().all()

        context = build_context_from_tasks(tasks)
        source_text = get_all_extracted_text(context)

        summary = ""
        model_used = "Unknown"

        # Prefer DeepSummarizer if both exist
        for name in [DEEP_SUMMARIZER_NAME, SUMMARIZER_NAME]:
            if name in context:
                summary_data = context[name]
                summary = summary_data.get("summary") or summary_data.get(
                    "extensive_summary", ""
                )
                model_used = summary_data.get("model", "Unknown")
                if summary:
                    break

        if source_text and summary:
            pairs.append(
                {
                    "path": doc.path,
                    "source_text": source_text,
                    "summary": summary,
                    "model_used": model_used,
                }
            )
        else:
            logger.debug(f"Skipping {doc.path}: Missing source text or summary data.")

    return pairs


async def evaluate_pair(llm, pair: Dict[str, Any]) -> Dict[str, Any]:
    """Use the LLM to judge a single summary."""
    source_text_capped = pair["source_text"][:8000]

    prompt = JUDGE_PROMPT.format(
        source_text=source_text_capped, summary=pair["summary"]
    )

    try:
        response_text = await llm.generate(
            prompt, response_format="json", temperature=0.0
        )
        evaluation = repair_and_load_json(response_text)

        if not evaluation:
            logger.error(f"Failed to parse LLM response as JSON: {response_text}")
            return {
                "error": "JSON parse error",
                "raw_response": response_text,
                "path": pair["path"],
            }

        evaluation["path"] = pair["path"]
        evaluation["model_used"] = pair["model_used"]
        return evaluation
    except Exception as e:
        logger.error(f"LLM evaluation failed for {pair['path']}: {e}")
        return {"error": str(e), "path": pair["path"]}


async def main():
    parser = argparse.ArgumentParser(
        description="Evaluate generated summaries using an LLM-as-a-judge."
    )
    parser.add_argument(
        "--samples", type=int, default=5, help="Number of random documents to sample."
    )
    parser.add_argument(
        "--output", type=str, help="Path to save evaluation results as JSON."
    )
    args = parser.parse_args()

    llm = get_llm_provider()
    if not llm or isinstance(llm, str):
        logger.error(f"Failed to initialize LLM provider: {llm}")
        return

    async with async_session_maker() as session:
        pairs = await get_summary_pairs(session, args.samples)

    if not pairs:
        logger.info(
            "No documents with completed summaries found that have source text."
        )
        return

    logger.info(f"Evaluating {len(pairs)} summaries...")

    results = []
    for i, pair in enumerate(pairs):
        logger.info(
            f"[{i+1}/{len(pairs)}] Evaluating {pair['path']} (Model: {pair['model_used']})..."
        )
        evaluation = await evaluate_pair(llm, pair)
        results.append(evaluation)

        if "error" not in evaluation:
            print(f"\nResults for: {evaluation['path']}")
            print(f"  Model Used: {evaluation['model_used']}")
            print(f"  Accuracy: {evaluation.get('accuracy')}/5")
            print(f"  Coverage: {evaluation.get('coverage')}/5")
            print(f"  Hallucination-free: {evaluation.get('hallucination_free')}/5")
            print(f"  Reasoning: {evaluation.get('reasoning')}")
        else:
            print(f"\nResults for: {evaluation['path']}")
            print(f"  Error: {evaluation['error']}")

    valid_results = [r for r in results if "error" not in r]
    if valid_results:
        avg_acc = sum(r["accuracy"] for r in valid_results) / len(valid_results)
        avg_cov = sum(r["coverage"] for r in valid_results) / len(valid_results)
        avg_hf = sum(r["hallucination_free"] for r in valid_results) / len(
            valid_results
        )

        print("\n" + "=" * 40)
        print("AGGREGATE EVALUATION RESULTS")
        print("=" * 40)
        print(f"Total Samples: {len(results)}")
        print(f"Valid Samples: {len(valid_results)}")
        print(f"Average Accuracy: {avg_acc:.2f}/5")
        print(f"Average Coverage: {avg_cov:.2f}/5")
        print(f"Average Hallucination-free: {avg_hf:.2f}/5")

        # Group by Model
        models = set(r["model_used"] for r in valid_results)
        if len(models) > 1:
            print("\nBREAKDOWN BY MODEL:")
            for m in models:
                m_results = [r for r in valid_results if r["model_used"] == m]
                m_acc = sum(r["accuracy"] for r in m_results) / len(m_results)
                print(f"  {m}: {m_acc:.2f} accuracy ({len(m_results)} samples)")

        print("=" * 40)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2)
        logger.info(f"Detailed results saved to {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
