"""Free-tier hosting compatibility: URLs from Neon / Supabase / Render / Heroku-style providers must just work."""
import pytest

from app.core.config import Settings, normalise_database_url


@pytest.mark.parametrize("raw,expected", [
    ("postgres://u:p@host/db", "postgresql+asyncpg://u:p@host/db"),
    ("postgresql://u:p@host:5432/db", "postgresql+asyncpg://u:p@host:5432/db"),
    ("postgresql://u:p@ep-x-pooler.neon.tech/db?sslmode=require", "postgresql+asyncpg://u:p@ep-x-pooler.neon.tech/db?ssl=require"),
    ("postgresql://u:p@h/db?sslmode=require&channel_binding=require", "postgresql+asyncpg://u:p@h/db?ssl=require"),
    ("postgres://u:p@h/db?sslmode=verify-full&application_name=x", "postgresql+asyncpg://u:p@h/db?ssl=verify-full"),
    ("postgresql+asyncpg://u:p@h/db?ssl=require", "postgresql+asyncpg://u:p@h/db?ssl=require"),
    ("sqlite+aiosqlite:///./x.db", "sqlite+aiosqlite:///./x.db"),
])
def test_database_url_normalisation(raw, expected):
    assert normalise_database_url(raw) == expected


def test_special_characters_in_password_survive():
    assert normalise_database_url("postgres://u:p%40ss%2Fw@h/db?sslmode=require") == "postgresql+asyncpg://u:p%40ss%2Fw@h/db?ssl=require"


def test_settings_applies_normalisation_and_detects_poolers():
    s = Settings(_env_file=None, database_url="postgresql://u:p@ep-abc-pooler.eu.neon.tech/db?sslmode=require")
    assert s.database_url.startswith("postgresql+asyncpg://") and "ssl=require" in s.database_url and s.uses_pgbouncer
    assert not Settings(_env_file=None, database_url="postgresql://u:p@db.internal/db").uses_pgbouncer
    assert Settings(_env_file=None, database_url="postgresql://u:p@db.internal:6543/db").uses_pgbouncer  # Supabase pooler port
    assert Settings(_env_file=None, db_pgbouncer=True).uses_pgbouncer


def test_free_tier_defaults_are_small():
    s = Settings(_env_file=None)
    assert s.db_pool_size + s.db_max_overflow <= 10


def test_production_accepts_free_provider_urls():
    s = Settings(_env_file=None, env="production", api_keys="k" * 24 + ":admin:acme", enc_key="a" * 64,
                 database_url="postgres://u:p@ep-x-pooler.neon.tech/db?sslmode=require", redis_url="rediss://default:pw@eu1-x.upstash.io:6379")
    assert s.is_prod and s.database_url.startswith("postgresql+asyncpg://")


def test_blueprint_and_dockerignore_present_and_safe():
    import yaml
    bp = yaml.safe_load(open("render.yaml", encoding="utf8"))
    svc = bp["services"][0]
    assert svc["plan"] == "free" and svc["runtime"] == "docker" and svc["healthCheckPath"] == "/healthz"
    env = {e["key"]: e for e in svc["envVars"]}
    for secret in ("DATABASE_URL", "REDIS_URL", "API_KEYS", "ENC_KEY"):
        assert env[secret].get("sync") is False and "value" not in env[secret], f"{secret} must not be stored in the blueprint"
    assert env["ENV"]["value"] == "production" and env["WEB_CONCURRENCY"]["value"] == "1" and env["DOCS_ENABLED"]["value"] == "false"
    ignored = open(".dockerignore", encoding="utf8").read()
    assert ".venv" in ignored and ".git" in ignored and ".env" in ignored
