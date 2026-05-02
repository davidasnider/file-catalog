import asyncio
import logging
import collections
import json
from typing import Dict, Any, Tuple, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models import Document, AnalysisTask, DocumentStatus, TaskStatus
from src.core.plugin_registry import ANALYZER_REGISTRY, get_ordered_analyzers
from sqlalchemy.orm import sessionmaker
from sqlmodel import select
from src.core.config import config

logger = logging.getLogger(__name__)


class TaskEngine:
    def __init__(
        self,
        async_session_maker: sessionmaker,
        max_concurrent_tasks: int = 5,
        mime_limit_ratio: float = 0.5,
        callbacks: Dict[str, Any] = None,
        abort_event: Optional[asyncio.Event] = None,
    ):
        self.max_concurrent_tasks = max_concurrent_tasks
        self.mime_limit_ratio = mime_limit_ratio
        self.async_session_maker = async_session_maker
        self.callbacks = callbacks or {}
        self.abort_event = abort_event

        # Concurrency management via Condition for finer-grained control (MIME balancing)
        self._condition = asyncio.Condition()
        self._active_total = 0
        self._active_counts = collections.defaultdict(int)
        self._queued_counts = collections.defaultdict(int)

    def _trigger(self, event_name: str, *args, **kwargs):
        if event_name in self.callbacks:
            try:
                self.callbacks[event_name](*args, **kwargs)
            except Exception:
                pass

    def request_abort(self):
        """Signal the engine to abort processing."""
        if self.abort_event:
            self.abort_event.set()

    async def notify_all(self):
        """Wake up all waiting tasks."""
        async with self._condition:
            self._condition.notify_all()

    def _get_mime_group(self, mime_type: Optional[str]) -> str:
        """Group MIME types by prefix (e.g. image/jpeg -> image)."""
        if not mime_type or "/" not in mime_type:
            return "unknown"
        return mime_type.split("/")[0]

    async def execute_plugin(
        self,
        task_name: str,
        document_path: str,
        mime_type: str,
        context: Dict[str, Any],
        session: AsyncSession,
        task_id: int,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Execute a single plugin with robust exception handling."""
        plugin_class = ANALYZER_REGISTRY.get(task_name)
        if not plugin_class:
            available_plugins = ", ".join(sorted(ANALYZER_REGISTRY.keys())) or "<none>"
            return (
                False,
                f"Plugin '{task_name}' not found in registry. "
                f"Available plugins: {available_plugins}. "
                "If this is unexpected, ensure all analyzer plugins have been imported and registered.",
                {},
            )

        retry_count = 0
        max_retries = config.max_retries

        while True:
            try:
                # Rehydrate the task to update status
                task = await session.get(AnalysisTask, task_id)
                if not task:
                    return False, f"Task {task_id} not found in DB", {}

                task.status = TaskStatus.IN_PROGRESS
                task.plugin_version = plugin_class._analyzer_version
                task.error_message = None
                task.retry_count = retry_count
                await session.commit()

                # Instantiate and check conditionally
                analyzer = plugin_class()
                if not analyzer.should_run(document_path, mime_type, context):
                    task = await session.get(AnalysisTask, task_id)
                    task.status = TaskStatus.COMPLETED
                    result = {
                        "skipped": True,
                        "reason": "Condition not met by should_run",
                    }
                    try:
                        task.result_data = json.dumps(result)
                    except TypeError:
                        logger.warning(
                            f"Could not serialize skip result for {task_name}, storing empty dict."
                        )
                        task.result_data = "{}"
                    await session.commit()
                    return True, "", result

                # Run the plugin
                result = await analyzer.analyze(document_path, mime_type, context)

                # Successful completion
                task = await session.get(AnalysisTask, task_id)
                task.status = TaskStatus.COMPLETED
                try:
                    task.result_data = json.dumps(result)
                except TypeError:
                    logger.warning(
                        f"Could not serialize result for {task_name}, storing empty dict."
                    )
                    task.result_data = "{}"

                await session.commit()
                return True, "", result

            except asyncio.CancelledError:
                raise
            except Exception as e:
                retry_count += 1
                if retry_count <= max_retries:
                    backoff = 2**retry_count
                    logger.warning(
                        f"Error executing plugin {task_name} on {document_path}: {e}. "
                        f"Retrying in {backoff}s ({retry_count}/{max_retries})..."
                    )
                    task = await session.get(AnalysisTask, task_id)
                    if task:
                        task.status = TaskStatus.RETRIES
                        task.error_message = str(e)
                        task.retry_count = retry_count
                        await session.commit()
                    await asyncio.sleep(backoff)
                    continue

                logger.error(
                    f"Plugin {task_name} failed after {max_retries} retries on {document_path}: {e}"
                )
                # Ensure task is marked as failed
                task = await session.get(AnalysisTask, task_id)
                if task:
                    task.status = TaskStatus.FAILED
                    task.error_message = str(e)
                    task.retry_count = retry_count
                    await session.commit()
                return False, str(e), {}

    async def process_document(self, document_id: int, mime_type: Optional[str] = None):
        """Process a document through all registered plugins using a MIME-aware scheduler."""
        doc_path = None
        # 1. Fetch document metadata to determine MIME group ONLY if mime_type is not provided.
        if not mime_type:
            async with self.async_session_maker() as session:
                doc = await session.get(Document, document_id)
                if not doc:
                    logger.error(f"Document {document_id} not found")
                    return False
                mime_type = doc.mime_type
                doc_path = doc.path

        if self.abort_event and self.abort_event.is_set():
            return False

        group = self._get_mime_group(mime_type)

        # 2. Acquire "slot" with MIME balancing logic
        async with self._condition:
            self._queued_counts[group] += 1
            # Notify others that queue state has changed (others_waiting might be true now)
            self._condition.notify_all()

            try:
                while True:
                    if self.abort_event and self.abort_event.is_set():
                        self._queued_counts[group] -= 1
                        self._condition.notify_all()
                        return False

                    # Capacity check
                    if self._active_total < self.max_concurrent_tasks:
                        active_in_group = self._active_counts[group]
                        # Check if others are waiting for ANY slot
                        others_waiting = any(
                            count > 0
                            for g, count in self._queued_counts.items()
                            if g != group
                        )

                        # MIME-aware limit: only 50% capacity for one group if others are waiting.
                        limit = int(self.max_concurrent_tasks * self.mime_limit_ratio)

                        if not others_waiting or active_in_group < limit:
                            # Success: take the slot
                            self._queued_counts[group] -= 1
                            self._active_counts[group] += 1
                            self._active_total += 1
                            break

                    # Wait for a notification that a slot has opened or queue state changed
                    await self._condition.wait()
            except asyncio.CancelledError:
                self._queued_counts[group] -= 1
                self._condition.notify_all()
                raise

        # 3. Execution phase
        try:
            async with self.async_session_maker() as session:
                # Refresh doc in new session
                doc = await session.get(Document, document_id)
                if not doc:
                    return False
                doc_path = doc.path
                self._trigger(
                    "doc_start", document_id, path=doc_path, mime_type=mime_type
                )

                try:
                    doc.status = DocumentStatus.ANALYZING
                    await session.commit()

                    context: Dict[str, Any] = {}
                    all_success = True

                    # Query existing tasks to handle versioning and skips
                    existing_tasks_result = await session.execute(
                        select(AnalysisTask).where(AnalysisTask.document_id == doc.id)
                    )
                    existing_tasks = {
                        t.task_name: t for t in existing_tasks_result.scalars().all()
                    }

                    all_analyzers = get_ordered_analyzers()
                    failed_plugins = set()

                    for plugin_name, plugin_class in all_analyzers:
                        current_version = plugin_class._analyzer_version
                        existing_task = existing_tasks.get(plugin_name)

                        # Check dependencies
                        plugin_deps = set(getattr(plugin_class, "_depends_on", []))
                        dep_failures = plugin_deps.intersection(failed_plugins)

                        if dep_failures:
                            logger.info(
                                f"Dependencies {dep_failures} for {plugin_name} on doc {document_id} have failed; "
                                "continuing with analyzer execution due to soft dependency semantics."
                            )

                        # Check if we can skip this task
                        if (
                            existing_task
                            and existing_task.status == TaskStatus.COMPLETED
                            and existing_task.plugin_version == current_version
                        ):
                            logger.info(
                                f"Skipping {plugin_name} (v{current_version}) for {document_id}, already completed."
                            )
                            if existing_task.result_data:
                                try:
                                    context[plugin_name] = json.loads(
                                        existing_task.result_data
                                    )
                                except json.JSONDecodeError as e:
                                    logger.warning(
                                        "Failed to decode cached result_data for plugin %s on document %s; using empty context. Error: %s",
                                        plugin_name,
                                        document_id,
                                        e,
                                    )
                                    context[plugin_name] = {}
                            else:
                                context[plugin_name] = {}
                            continue

                        # Run or re-run
                        if existing_task:
                            task = existing_task
                            task.status = TaskStatus.PENDING
                            task.error_message = None
                            task.plugin_version = current_version
                        else:
                            task = AnalysisTask(
                                document_id=doc.id,
                                task_name=plugin_name,
                                status=TaskStatus.PENDING,
                                plugin_version=current_version,
                            )
                            session.add(task)

                        await session.commit()
                        await session.refresh(task)

                        self._trigger(
                            "plugin_start",
                            document_id,
                            plugin_name,
                            path=doc.path,
                            mime_type=doc.mime_type,
                        )

                        success, err, result = await self.execute_plugin(
                            task_name=plugin_name,
                            document_path=doc.path,
                            mime_type=doc.mime_type,
                            context=context,
                            session=session,
                            task_id=task.id,
                        )

                        if success:
                            context[plugin_name] = result
                        else:
                            all_success = False
                            failed_plugins.add(plugin_name)

                    doc = await session.get(Document, document_id)
                    doc.status = (
                        DocumentStatus.COMPLETED
                        if all_success
                        else DocumentStatus.FAILED
                    )
                    await session.commit()
                    return True

                except asyncio.CancelledError:
                    logger.warning(f"Processing cancelled for document {document_id}")
                    doc = await session.get(Document, document_id)
                    if doc:
                        doc.status = DocumentStatus.FAILED
                        await session.commit()
                    raise
                except Exception as e:
                    logger.error(
                        f"Unexpected error processing document {document_id}: {e}"
                    )
                    doc = await session.get(Document, document_id)
                    if doc:
                        doc.status = DocumentStatus.FAILED
                        await session.commit()
                    return False
        finally:
            # 4. Release slot
            async with self._condition:
                self._active_counts[group] -= 1
                self._active_total -= 1
                self._condition.notify_all()
            self._trigger("doc_end", document_id)
