"""Database singleton + Unit of Work (async SQLAlchemy over asyncpg/PostgreSQL)."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.infra.orm import Base


class Database:
    """Singleton wrapper: one engine/pool per process."""
    _instance: "Database | None" = None

    def __init__(self, url: str):
        kwargs: dict = {"future": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            if ":memory:" in url:
                kwargs["poolclass"] = StaticPool
        else:
            kwargs.update(pool_size=10, max_overflow=10, pool_pre_ping=True, pool_recycle=1800, pool_timeout=10,
                          connect_args={"timeout": 10, "command_timeout": 30})
        self.engine: AsyncEngine = create_async_engine(url, **kwargs)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    @classmethod
    def instance(cls) -> "Database":
        if cls._instance is None:
            cls._instance = cls(get_settings().database_url)
        return cls._instance

    @classmethod
    async def dispose(cls) -> None:
        if cls._instance:
            await cls._instance.engine.dispose()
            cls._instance = None

    async def create_schema(self) -> None:
        async with self.engine.begin() as conn:
            if conn.dialect.name == "postgresql":  # several gunicorn workers boot at once: serialise DDL
                await conn.execute(text("SELECT pg_advisory_xact_lock(727274)"))
            await conn.run_sync(Base.metadata.create_all)

    async def ping(self) -> bool:
        async with self.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True

    def uow(self) -> "UnitOfWork":
        from app.infra.uow import UnitOfWork
        return UnitOfWork(self.sessionmaker)
