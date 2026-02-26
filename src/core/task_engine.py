import asyncio
import logging
from typing import Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker
from src.db.models import Document, AnalysisTask, DocumentStatus, TaskStatus
from src.core.plugin_registry import ANALYZER_REGISTRY

logger = logging.getLogger(__name__)


class TaskEngine:
    def __init__(
        self, async_session_maker: sessionmaker, max_concurrent_tasks: int = 5
    ):
        self.semaphore = asyncio.Semaphore(max_concurrent_tasks)
        self.async_session_maker = async_session_maker

    async def execute_plugin(
        self,
        task_name: str,
        document_path: str,
        mime_type: str,
        context: Dict[str, Any],
        session: AsyncSession,
        task_id: int,
    ) -> Tuple[bool, str]:
        """Execute a single plugin with robust exception handling."""
        plugin_class = ANALYZER_REGISTRY.get(task_name)
        if not plugin_class:
            return False, f"Plugin {task_name} not found in registry"

        try:
            # Rehydrate the task to update status
            task = await session.get(AnalysisTask, task_id)
            if not task:
                return False, f"Task {task_id} not found in DB"

            task.status = TaskStatus.IN_PROGRESS
            await session.commit()

            # Instantiate and run
            analyzer = plugin_class()
            result = await analyzer.analyze(document_path, mime_type, context)

            # Successful completion
            task = await session.get(AnalysisTask, task_id)
            task.status = TaskStatus.COMPLETED
            await session.commit()

            context[task_name] = result  # Make result available to next plugins
            return True, ""

        except Exception as e:
            logger.error(f"Error executing plugin {task_name} on {document_path}: {e}")
            # Ensure task is marked as failed
            task = await session.get(AnalysisTask, task_id)
            if task:
                task.status = TaskStatus.FAILED
                task.error_message = str(e)
                await session.commit()
            return False, str(e)

    async def process_document(self, document_id: int):
        """Process a document through all registered plugins using a bounded semaphore."""
        async with self.semaphore:
            async with self.async_session_maker() as session:
                doc = await session.get(Document, document_id)
                if not doc:
                    logger.error(f"Document {document_id} not found")
                    return

                try:
                    doc.status = DocumentStatus.ANALYZING
                    await session.commit()

                    context: Dict[str, Any] = {}

                    # Currently running all registered plugins sequentially for a single document
                    # To support complex `depends_on` we would build a DAG and execute async task groups
                    # For this V2 MVP we iterate through them.
                    all_success = True

                    for plugin_name in ANALYZER_REGISTRY.keys():
                        # Create DB record for this specific task
                        task = AnalysisTask(
                            document_id=doc.id,
                            task_name=plugin_name,
                            status=TaskStatus.PENDING,
                        )
                        session.add(task)
                        await session.commit()
                        await session.refresh(task)

                        success, err = await self.execute_plugin(
                            task_name=plugin_name,
                            document_path=doc.path,
                            mime_type=doc.mime_type,
                            context=context,
                            session=session,
                            task_id=task.id,
                        )
                        if not success:
                            all_success = False
                            break  # Stop pipeline for this doc on first failure (or we could continue depending on requirements)

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
