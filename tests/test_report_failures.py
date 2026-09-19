"""Tests for src/scripts/report_failures.py summary stats helpers."""

from unittest import mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from src.db.models import Document, DocumentStatus
from src.scripts import report_failures


@pytest.fixture
def rf_session(test_engine):
    """Patch the module's session maker to use the in-memory test engine."""
    maker = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    with mock.patch.object(report_failures, "async_session_maker", maker):
        yield maker


async def test_get_summary_stats_counts_failed_docs_independently(
    db_session, rf_session
):
    """Calling get_summary_stats() without a failures list must still count
    documents whose status is FAILED (regression: it previously reported 0).
    """
    db_session.add_all(
        [
            Document(
                path="/data/a.pdf",
                mime_type="application/pdf",
                status=DocumentStatus.FAILED,
            ),
            Document(
                path="/data/b.pdf",
                mime_type="application/pdf",
                status=DocumentStatus.COMPLETED,
            ),
            Document(
                path="/data/c.txt",
                mime_type="text/plain",
                status=DocumentStatus.PENDING,
            ),
        ]
    )
    await db_session.commit()

    stats = dict(await report_failures.get_summary_stats())

    assert stats["application/pdf"]["FAILED"] == 1
    assert stats["application/pdf"]["COMPLETED"] == 1
    assert stats["text/plain"]["PENDING"] == 1


async def test_get_summary_stats_failures_refine_failed_counts(db_session, rf_session):
    """When a failures list is supplied, task-level failures whose document
    status has not flipped to FAILED are counted as FAILED.
    """
    doc = Document(
        path="/data/x.pdf",
        mime_type="application/pdf",
        status=DocumentStatus.PENDING,
    )
    db_session.add(doc)
    await db_session.commit()

    failures = [
        {
            "type": "task",
            "document_id": doc.id,
            "path": doc.path,
            "mime_type": doc.mime_type,
            "task_name": "TextExtractor",
            "error_message": "boom",
        }
    ]

    stats = dict(await report_failures.get_summary_stats(failures=failures))

    assert stats["application/pdf"]["FAILED"] == 1
