# core/database.py — async SQLAlchemy engine, session factory, and Base class
# Every model imports Base from here. Never define Base elsewhere.
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from core.config import settings


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.APP_ENV == "development",  # logs SQL queries in dev only
    pool_pre_ping=True,    # drops stale connections automatically
    pool_size=5,
    max_overflow=10,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # keep ORM objects usable after commit
)


class Base(DeclarativeBase):
    """Single declarative base — all models inherit from this."""
    pass


async def get_db():
    """
    FastAPI dependency — inject with: db: AsyncSession = Depends(get_db)
    Commits on success, rolls back on any exception (including HTTPException).
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        # No finally close needed — AsyncSessionLocal context manager handles it


async def init_db():
    """
    Creates all tables on first run.
    Called from main.py lifespan startup.
    Production uses Alembic migrations instead.
    """
    async with engine.begin() as conn:
        import core.models  # noqa: F401 — ensures models are registered on Base
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """Dispose connection pool on app shutdown."""
    await engine.dispose()
