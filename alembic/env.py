"""Alembic environment (async engine). Usage:  alembic upgrade head   |   alembic revision --autogenerate -m "msg"
DATABASE_URL is read from the environment (same variable as the app)."""
import asyncio
import os

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import normalise_database_url
from app.infra.orm import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return normalise_database_url(os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./regguard.db"))


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as conn:
        await conn.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
