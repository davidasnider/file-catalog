from enum import Enum
from typing import Optional, List
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel, Relationship
from datetime import datetime, timezone


class DocumentStatus(str, Enum):
    PENDING = "PENDING"
    EXTRACTING = "EXTRACTING"
    ANALYZING = "ANALYZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    NOT_PRESENT = "NOT_PRESENT"
    # Core status used for filesystem synchronization. It is used to mark files
    # that were previously cataloged but are now deleted or missing from their
    # original location on disk. When the system runs an incremental scan and
    # detects that a file is missing, its status is set to NOT_PRESENT (bypassing
    # the standard processing pipeline). Crucially, when a document transitions
    # to this state, it is automatically purged from the Full-Text Search (FTS)
    # index, ensuring that search results remain accurate and do not surface stale
    # data for files that no longer exist.


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETRIES = "RETRIES"


class Document(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    path: str = Field(index=True, unique=True, description="Absolute path to the file")
    mime_type: Optional[str] = Field(
        default=None, description="Robustly detected MIME type"
    )
    file_hash: Optional[str] = Field(
        default=None,
        index=True,
        description="Hash of the file contents to prevent duplicate processing",
    )
    file_size: Optional[int] = Field(
        default=None, description="Size of the file in bytes"
    )
    mtime: Optional[float] = Field(
        default=None, description="Modification time of the file (POSIX timestamp)"
    )
    # Use SAEnum with create_constraint=False to map to string storage while keeping Python enum
    status: DocumentStatus = Field(
        default=DocumentStatus.PENDING,
        sa_type=SAEnum(DocumentStatus, native_enum=False, create_constraint=False),
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    tasks: List["AnalysisTask"] = Relationship(back_populates="document")


class AnalysisTask(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document.id", index=True)
    task_name: str = Field(
        description="Name of the analysis task (e.g., OCR, Text Splitting)"
    )
    plugin_version: str = Field(
        default="1.0", description="Version of the plugin that executed this task"
    )
    status: TaskStatus = Field(
        default=TaskStatus.PENDING,
        sa_type=SAEnum(TaskStatus, native_enum=False, create_constraint=False),
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    judged_at: Optional[datetime] = Field(
        default=None, description="Timestamp when the task was last judged"
    )
    error_message: Optional[str] = Field(
        default=None, description="Error message if the task failed"
    )
    result_data: Optional[str] = Field(
        default=None, description="JSON serialized results of the task execution"
    )
    retry_count: int = Field(
        default=0, description="Number of times this task has been retried"
    )

    document: Document = Relationship(back_populates="tasks")
