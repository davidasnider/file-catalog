import json
import logging
import asyncio
import os
from typing import Dict, Any, Optional
from rich.console import Console
from src.core.config import config
from src.core.text_utils import repair_and_load_json, get_all_extracted_text
from src.core.analyzer_names import (
    SUMMARIZER_NAME,
    DEEP_SUMMARIZER_NAME,
    PII_HARVESTER_NAME,
    VISION_ANALYZER_NAME,
)

logger = logging.getLogger(__name__)
console = Console()

CORRECTIONS_FILE = "judge_corrections.json"
_console_lock = asyncio.Lock()


class TaskJudge:
    def __init__(self, provider=None):
        self._provider = provider
        self.corrections_path = CORRECTIONS_FILE
        self.is_interacting = False

    @property
    def provider(self):
        if self._provider is None:
            from src.llm.factory import get_llm_provider

            self._provider = get_llm_provider()
        return self._provider

    async def judge_task(
        self,
        task_name: str,
        doc_path: str,
        result: Dict[str, Any],
        context: Dict[str, Any],
    ) -> str:
        """
        Judges a task.
        Returns 'PASSED', 'FAILED', 'SKIPPED', or 'ERROR'.
        """
        if not config.judge_enabled:
            return "SKIPPED"

        # Check if the task was skipped during analysis
        if result.get("skipped"):
            return "SKIPPED"

        # Check for execution errors first
        if "error" in result and result.get("status") == "FAILED":
            eval_data = {
                "reasoning": f"Execution Error: {result.get('error')}",
                "accuracy": 1,
                "hallucination_free": 1,
                "precision": 1,
                "recall": 1,
                "coherence": 1,
            }
            await self._handle_failure(task_name, doc_path, result, context, eval_data)
            return "FAILED"

        # 1. Determine evaluation prompt based on task_name
        eval_prompt = self._get_evaluation_prompt(task_name, result, context)
        if not eval_prompt:
            return "SKIPPED"  # Not judgeable or skipped

        # 2. Run LLM Judge
        try:
            # We use a high-quality model if possible, or the default provider.
            # We omit response_format="json" because some local endpoints (like standard mlx-lm servers)
            # might silently return empty strings if JSON mode is not explicitly supported.
            # We pass the maximum supported tokens because reasoning models (like Qwen) use extensive tokens for thinking.
            max_out = await self.provider.get_safe_output_tokens(eval_prompt)
            response = await self.provider.generate(
                eval_prompt, temperature=0.0, max_tokens=max_out
            )
            eval_data = repair_and_load_json(response)
        except Exception as e:
            logger.error(f"Judge failed for {task_name} on {doc_path}: {e}")
            eval_data = {"reasoning": f"Judge LLM Execution Error: {e}"}
            await self._handle_failure(task_name, doc_path, result, context, eval_data)
            return "ERROR"

        if not eval_data:
            logger.warning(
                f"Judge returned empty or invalid JSON for {task_name} on {doc_path}. Raw: {response}"
            )
            display_resp = str(response) if response else "EMPTY_RESPONSE"
            if len(display_resp) > 500:
                display_resp = display_resp[:500] + "..."

            eval_data = {
                "reasoning": f"Judge returned empty or invalid JSON.\nRaw output:\n{display_resp}"
            }
            await self._handle_failure(task_name, doc_path, result, context, eval_data)
            return "ERROR"

        # 3. Check if it passed
        passed = self._check_passed(task_name, eval_data)

        if not passed:
            await self._handle_failure(task_name, doc_path, result, context, eval_data)
            return "FAILED"

        return "PASSED"

    async def _handle_failure(
        self,
        task_name: str,
        doc_path: str,
        result: Dict[str, Any],
        context: Dict[str, Any],
        eval_data: Dict[str, Any],
    ) -> bool:
        """Helper to handle the feedback loop for failed tasks or low-quality results."""
        # 4. Feedback loop
        async with _console_lock:
            from rich.panel import Panel
            from rich.text import Text

            # Prepare sections
            source_material = get_all_extracted_text(context) or "N/A (Vision/Binary)"

            original_prompt = result.get("prompt")
            if not original_prompt:
                # Dynamically construct the current prompt for legacy tasks
                if task_name == SUMMARIZER_NAME:
                    original_prompt = f"""You are an expert document summarizer analyzing a local digital archive. Read the following text extracted from a file and provide a concise, 3-sentence summary of the core content.

CRITICAL INSTRUCTIONS:
1. Return ONLY the 3-sentence summary.
2. Accurately identify the roles of individuals (e.g., strictly distinguish between the customer/account holder and service providers/technicians). Do not conflate names with incorrect titles.
3. Ensure absolute factual alignment with the source text. Do not make assumptions.
4. DO NOT output any thinking process. NO <think> tags. NO "Here is a thinking process".
5. Do NOT include any conversational filler, preambles, or introductory text.
6. Begin exactly with the first sentence of the summary.

Text:
{source_material}"""
                elif task_name == PII_HARVESTER_NAME:
                    original_prompt = f"Identify Personally Identifiable Information (PII) from the following text:\n{source_material}"
                else:
                    original_prompt = "N/A (Prompt not captured or execution failed)"

            if len(source_material) > 1000:
                source_material = source_material[:1000] + "..."
            ai_output = json.dumps(result, indent=2)
            if len(ai_output) > 1000:
                ai_output = ai_output[:1000] + "..."

            console.print("\n" + "=" * 80, style="bold red")
            console.print(
                "FAILED QUALITY CHECK / EXECUTION ERROR",
                style="bold white on red",
                justify="center",
            )
            console.print(
                f"Task: [bold cyan]{task_name}[/bold cyan] | File: [dim]{doc_path}[/dim]",
                justify="center",
            )
            console.print("-" * 80)

            console.print(
                Panel(
                    Text(source_material),
                    title="[bold green]Source Material (Snippet)[/bold green]",
                    border_style="green",
                    padding=(1, 2),
                )
            )

            console.print(
                Panel(
                    Text(original_prompt),
                    title="[bold yellow]Original Prompt (Copy/Edit this)[/bold yellow]",
                    border_style="yellow",
                    padding=(1, 2),
                )
            )

            console.print(
                Panel(
                    Text(ai_output),
                    title="[bold blue]AI Output / Error (Snippet)[/bold blue]",
                    border_style="blue",
                    padding=(1, 2),
                )
            )

            console.print(
                f"[bold red]Judge/Error Reasoning:[/bold red] {eval_data.get('reasoning', 'No reasoning provided')}"
            )
            console.print("=" * 80, style="bold red")

            # Standalone judge mode: just show the details, no input prompt.
            # The user can copy/paste the original prompt to manually iterate.
            return False  # Signal failure

        return True

    def _get_evaluation_prompt(
        self, task_name: str, result: Dict[str, Any], context: Dict[str, Any]
    ) -> Optional[str]:
        source_text = get_all_extracted_text(context)
        if not source_text and task_name not in [VISION_ANALYZER_NAME]:
            return None

        # Cap source text for the judge
        is_truncated = bool(source_text and len(source_text) > 10000)
        source_text_capped = source_text[:10000] if source_text else ""
        if is_truncated:
            source_text_capped += "\n\n[...SOURCE TEXT TRUNCATED FOR EVALUATION...]"

        if task_name in [SUMMARIZER_NAME, DEEP_SUMMARIZER_NAME]:
            summary = result.get("summary") or result.get("extensive_summary", "")

            truncation_warning = ""
            if is_truncated:
                truncation_warning = "WARNING: The source text has been truncated due to length limits. DO NOT penalize the summary for 'hallucinations' if the details reasonably could have appeared later in the document. Only flag obvious fabrications that conflict with the visible text."

            return f"""
You are an expert quality assurance agent evaluating document summaries.
Compare the SOURCE TEXT with the GENERATED SUMMARY.

{truncation_warning}

SOURCE TEXT:
{source_text_capped}

GENERATED SUMMARY:
{summary}

EVALUATION CRITERIA:
1. Accuracy (1-5): Does the summary correctly represent facts visible in the text?
2. Coverage (1-5): Does it capture important points? (Be lenient if text is truncated).
3. Hallucination (1-5): 5 means no hallucinations, 1 means many. (DO NOT dock points for information that could be in the truncated portion).

Return JSON:
{{
    "accuracy": 1-5,
    "coverage": 1-5,
    "hallucination_free": 1-5,
    "reasoning": "Explanation"
}}
"""
        elif task_name == PII_HARVESTER_NAME:
            pii_data = result.get("pii", {})
            return f"""
You are an expert QA evaluating PII (Personally Identifiable Information) extraction.
Check if the extracted PII is accurate and if any major PII was missed.

SOURCE TEXT:
{source_text_capped}

EXTRACTED PII:
{json.dumps(pii_data, indent=2)}

EVALUATION CRITERIA:
1. Precision (1-5): Is the extracted info actually PII and correct?
2. Recall (1-5): Did it find most PII in the text?

Return JSON:
{{
    "precision": 1-5,
    "recall": 1-5,
    "reasoning": "Explanation"
}}
"""
        elif task_name == VISION_ANALYZER_NAME:
            # Vision is harder without the image, but we can check the description for consistency
            return f"""
You are an expert QA evaluating image analysis.
Since you can't see the image, evaluate if the description is coherent and logically consistent with the detected objects/text.

ANALYSIS:
{json.dumps(result, indent=2)}

EVALUATION CRITERIA:
1. Coherence (1-5): Is the description self-consistent?

Return JSON:
{{
    "coherence": 1-5,
    "reasoning": "Explanation"
}}
"""
        # Add more handlers as needed
        return None

    def _check_passed(self, task_name: str, eval_data: Dict[str, Any]) -> bool:
        if task_name in [SUMMARIZER_NAME, DEEP_SUMMARIZER_NAME]:
            accuracy = eval_data.get("accuracy")
            coverage = eval_data.get("coverage")
            hallucination_free = eval_data.get("hallucination_free")
            if (
                not isinstance(accuracy, (int, float))
                or not isinstance(coverage, (int, float))
                or not isinstance(hallucination_free, (int, float))
            ):
                return False
            return accuracy >= 4 and coverage >= 4 and hallucination_free >= 4
        elif task_name == PII_HARVESTER_NAME:
            precision = eval_data.get("precision")
            recall = eval_data.get("recall")
            if not isinstance(precision, (int, float)) or not isinstance(
                recall, (int, float)
            ):
                return False
            return precision >= 4 and recall >= 4
        elif task_name == VISION_ANALYZER_NAME:
            coherence = eval_data.get("coherence")
            if not isinstance(coherence, (int, float)):
                return False
            return coherence >= 4

        # Default pass if unknown scores
        return True

    def _record_correction(
        self,
        task_name: str,
        doc_path: str,
        result: Any,
        eval_data: Any,
        improved_prompt: str,
    ):
        from datetime import datetime, timezone

        record = {
            "task_name": task_name,
            "document_path": doc_path,
            "original_result": result,
            "judge_evaluation": eval_data,
            "improved_prompt": improved_prompt,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        try:
            data = []
            if os.path.exists(self.corrections_path):
                with open(self.corrections_path, "r") as f:
                    data = json.load(f)

            data.append(record)

            with open(self.corrections_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to record correction: {e}")
