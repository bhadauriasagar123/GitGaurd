import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")  # override with a postgresql+asyncpg:// URL to run the suite on PostgreSQL
os.environ.update({
    "ENV": "test",
    "REDIS_URL": os.environ.get("TEST_REDIS_URL", "fakeredis://"),  # CI sets TEST_REDIS_URL to a REAL Redis service container
    "API_KEYS": "admin-key-0000000000000001:admin:bank-a,analyst-key-00000000002:analyst:bank-a,viewer-key-000000000003:viewer:bank-a,other-tenant-key-0000004:admin:bank-b",
    "RATE_GENERAL": "100000",
    "RATE_LIMIT_HEAVY": "100000",
    "RATE_HEAVY": "100000",
})

# Hermetic: the suite must NEVER read a developer's real .env (it may hold live Neon/Upstash URLs and keys).
from app.core.config import Settings  # noqa: E402

Settings.model_config["env_file"] = None

import httpx
import pytest_asyncio

from app.api import deps
from app.core.config import reset_settings_cache
from app.infra.db import Database
from app.infra import redis_client

ADMIN = {"Authorization": "Bearer admin-key-0000000000000001"}
ANALYST = {"Authorization": "Bearer analyst-key-00000000002"}
VIEWER = {"Authorization": "Bearer viewer-key-000000000003"}
OTHER = {"Authorization": "Bearer other-tenant-key-0000004"}


@pytest_asyncio.fixture
async def client():
    reset_settings_cache()
    deps.reset_key_ring()
    await Database.dispose()
    await redis_client.close_redis()
    from app.infra.orm import Base
    async with Database.instance().engine.begin() as conn:  # clean slate (matters for persistent Postgres)
        await conn.run_sync(Base.metadata.drop_all)
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        if os.environ.get("TEST_REDIS_URL"):
            await app.state.container.redis.flushdb()  # isolate tests on a shared real Redis
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
