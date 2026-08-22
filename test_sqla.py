import asyncio
from sqlmodel import select, SQLModel, Field
from sqlalchemy.ext.asyncio import create_async_engine

class Document(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    path: str
    mime_type: str

async def main():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    stmt = select(Document).where(Document.path.endswith(".txt", autoescape=True))
    print(stmt.compile(engine, compile_kwargs={"literal_binds": True}))

    stmt2 = select(Document).where(Document.mime_type.contains("text", autoescape=True))
    print(stmt2.compile(engine, compile_kwargs={"literal_binds": True}))

asyncio.run(main())
