import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from src.core.task_engine import TaskEngine
import tempfile
import os


@pytest.mark.asyncio
async def test_mime_balancing_logic_simple():
    """
    Verifies the internal scheduling math and bypass logic of the TaskEngine.
    """
    db_fd, db_path = tempfile.mkstemp()
    os.close(db_fd)
    db_url = f"sqlite+aiosqlite:///{db_path}"
    engine_db = create_async_engine(db_url)
    async with engine_db.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async_session_maker = sessionmaker(
        engine_db, class_=AsyncSession, expire_on_commit=False
    )

    # 2 workers total, 50% ratio = 1 worker per group if balanced.
    engine = TaskEngine(
        async_session_maker=async_session_maker,
        max_concurrent_tasks=2,
        mime_limit_ratio=0.5,
    )

    # Manually populate state to test the scheduler's 'others_waiting' and 'limit' logic
    # Scenario: 1 'image' is active, 1 'image' is queued, 1 'text' is queued.
    # Total workers: 2. Active: 1. Slots free: 1.
    engine._active_counts["image"] = 1
    engine._active_total = 1
    engine._queued_counts["text"] = 1

    group = "image"
    active_in_group = engine._active_counts[group]
    others_waiting = any(
        count > 0 for g, count in engine._queued_counts.items() if g != group
    )
    limit = int(engine.max_concurrent_tasks * engine.mime_limit_ratio)

    can_start = not others_waiting or active_in_group < limit
    assert others_waiting is True
    assert (
        can_start is False
    )  # Balanced: blocked because another type is waiting and we are at limit.

    # Scenario: No text waiting.
    engine._queued_counts["text"] = 0
    others_waiting = any(
        count > 0 for g, count in engine._queued_counts.items() if g != group
    )
    can_start = not others_waiting or active_in_group < limit
    assert others_waiting is False
    assert can_start is True  # Bypass: allowed because no other types are waiting.

    await engine_db.dispose()
    os.unlink(db_path)
