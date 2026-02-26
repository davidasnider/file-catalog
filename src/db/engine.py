import logging
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

logger = logging.getLogger(__name__)

DATABASE_URL = "sqlite+aiosqlite:///./file_catalog.db"

# Create async engine
engine = create_async_engine(DATABASE_URL, echo=False, future=True)

# Create an async session maker
async_session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """Initialize the database schema."""
    logger.info("Initializing database...")
    async with engine.begin() as conn:
        # For our test scripts we drop everything first for a clean run
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    logger.info("Database initialization complete.")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for providing a database session."""
    async with async_session_maker() as session:
        yield session
