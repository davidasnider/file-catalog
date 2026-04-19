import logging
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlalchemy import event

logger = logging.getLogger(__name__)

DATABASE_URL = "sqlite+aiosqlite:///./file_catalog.db"

# Create async engine
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    pool_size=20,
    max_overflow=30,
)


@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=60000")  # 60 seconds
    cursor.close()


# Create an async session maker
async_session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    """Initialize the database schema."""
    logger.info("Initializing database...")
    async with engine.begin() as conn:
        try:
            # Check for our new columns to trigger a schema refresh if needed.
            # We check both the latest Document columns and AnalysisTask columns.
            await conn.execute(text("SELECT file_size, mtime FROM document LIMIT 1"))
            await conn.execute(
                text("SELECT plugin_version, retry_count FROM analysistask LIMIT 1")
            )
        except OperationalError:
            logger.info(
                "Outdated schema detected (missing file_size, mtime, or AnalysisTask enhancements), dropping tables for migration..."
            )
            await conn.execute(text("DROP TABLE IF EXISTS document_fts"))
            await conn.run_sync(SQLModel.metadata.drop_all)

        await conn.run_sync(SQLModel.metadata.create_all)

        # Create FTS5 virtual table
        await conn.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS document_fts USING fts5("
                "document_id UNINDEXED, "
                "path, "
                "content, "
                "summary"
                ");"
            )
        )
    logger.info("Database initialization complete.")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for providing a database session."""
    async with async_session_maker() as session:
        yield session
