import asyncio
import logging
from typing import Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
import json
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
        callbacks: Dict[str, Any] = None,
    ):
        self.semaphore = asyncio.Semaphore(max_concurrent_tasks)
        self.async_session_maker = async_session_maker
        self.callbacks = callbacks or {}

    def _trigger(self, event_name: str, *args, **kwargs):
        if event_name in self.callbacks:
            try:
                self.callbacks[event_name](*args, **kwargs)
            except Exception:
                pass

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

    async def process_document(self, document_id: int):
        """Process a document through all registered plugins using a bounded semaphore."""
        async with self.semaphore:
            async with self.async_session_maker() as session:
                doc = await session.get(Document, document_id)
                if not doc:
                    logger.error(f"Document {document_id} not found")
                    return

                self._trigger(
                    "doc_start", document_id, path=doc.path, mime_type=doc.mime_type
                )

                try:
                    doc.status = DocumentStatus.ANALYZING
                    await session.commit()

                    context: Dict[str, Any] = {}

                    # Currently running all registered plugins sequentially for a single document
                    # To support complex `depends_on` we would build a DAG and execute async task groups
                    # For this V2 MVP we iterate through them.
                    all_success = True

                    # Query existing tasks to handle versioning and skips
                    existing_tasks_result = await session.execute(
                        select(AnalysisTask).where(AnalysisTask.document_id == doc.id)
                    )
                    existing_tasks = {
                        t.task_name: t for t in existing_tasks_result.scalars().all()
                    }

                    all_success = True
                    all_analyzers = get_ordered_analyzers()
                    failed_plugins = set()

                    for plugin_name, plugin_class in all_analyzers:
                        current_version = plugin_class._analyzer_version
                        existing_task = existing_tasks.get(plugin_name)

                        # Check dependencies
                        plugin_deps = set(getattr(plugin_class, "_depends_on", []))
                        dep_failures = plugin_deps.intersection(failed_plugins)

                        if dep_failures:
                            # Some dependencies failed, but we treat depends_on as an ordering hint by default
                            # and allow analyzers to handle partial/empty context themselves.
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
                                        "Failed to decode cached result_data for plugin %s on document %s; "
                                        "using empty context instead. Error: %s",
                                        plugin_name,
                                        document_id,
                                        e,
                                    )
                                    context[plugin_name] = {}
                            else:
                                context[plugin_name] = {}
                            continue

                        # We need to run or re-run the task
                        if existing_task:
                            task = existing_task
                            task.status = TaskStatus.PENDING
                            task.error_message = None
                            task.plugin_version = current_version
                            logger.info(
                                f"Re-running {plugin_name} for {document_id} (Status: {existing_task.status}, Version: {existing_task.plugin_version} -> {current_version})"
                            )
                        else:
                            task = AnalysisTask(
                                document_id=doc.id,
                                task_name=plugin_name,
                                status=TaskStatus.PENDING,
                                plugin_version=current_version,
                            )
                            session.add(task)
                            logger.info(
                                f"Running new task {plugin_name} (v{current_version}) for {document_id}"
                            )

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
                            logger.warning(
                                f"Plugin {plugin_name} failed. Dependent plugins will be skipped for doc {document_id}."
                            )

                    doc = await session.get(Document, document_id)
                    if all_success:
                        doc.status = DocumentStatus.COMPLETED
                    else:
                        doc.status = DocumentStatus.FAILED

                    await session.commit()

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

        self._trigger("doc_end", document_id)
