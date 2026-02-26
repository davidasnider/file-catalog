from enum import Enum
from typing import Optional, List
from sqlmodel import Field, SQLModel, Relationship
from datetime import datetime, timezone


class DocumentStatus(str, Enum):
    PENDING = "PENDING"
    EXTRACTING = "EXTRACTING"
    ANALYZING = "ANALYZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


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
    status: DocumentStatus = Field(default=DocumentStatus.PENDING)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    tasks: List["AnalysisTask"] = Relationship(back_populates="document")


class AnalysisTask(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document.id", index=True)
    task_name: str = Field(
        description="Name of the analysis task (e.g., OCR, Text Splitting)"
    )
    status: TaskStatus = Field(default=TaskStatus.PENDING)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error_message: Optional[str] = Field(
        default=None, description="Error message if the task failed"
    )

    document: Document = Relationship(back_populates="tasks")
