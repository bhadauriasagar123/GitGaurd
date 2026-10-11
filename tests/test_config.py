import pytest

from app.core.config import Settings


def prod(**kw):
    base = dict(env="production", api_keys="k" * 24 + ":admin:acme", enc_key="a" * 64,
                database_url="postgresql+asyncpg://u:p@h/db", redis_url="rediss://h:6379")
    base.update(kw)
    return Settings(_env_file=None, **base)


def test_production_valid_config():
    s = prod()
    assert s.is_prod and s.key_ring()[0]["role"] == "admin" and "k" * 24 not in str(s.key_ring())  # keys stored hashed only


@pytest.mark.parametrize("override", [{"api_keys": ""}, {"enc_key": "short"}, {"redis_url": "fakeredis://"},
                                      {"database_url": "sqlite+aiosqlite:///x.db"}])
def test_production_refuses_insecure_defaults(override):
    with pytest.raises(ValueError):
        prod(**override)


def test_weak_or_malformed_keys_rejected_in_production():
    with pytest.raises(ValueError):
        prod(api_keys="short:admin:acme").key_ring()
    with pytest.raises(ValueError):
        prod(api_keys="k" * 24 + ":root:acme").key_ring()
    with pytest.raises(ValueError):
        prod(api_keys="k" * 24 + ":admin").key_ring()


def test_suite_is_hermetic_and_never_reads_a_real_dotenv(tmp_path, monkeypatch):
    """A developer's .env (live Neon/Upstash URLs, real keys) must not leak into tests."""
    import os
    from app.core.config import Settings, reset_settings_cache
    (tmp_path / ".env").write_text("REDIS_URL=rediss://default:SECRET@live.upstash.io:6379\nDATABASE_URL=postgres://u:LIVEPASS@neon/db\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    reset_settings_cache()
    s = Settings()
    assert s.redis_url == "fakeredis://" and s.database_url.startswith("sqlite") and "LIVEPASS" not in s.database_url
    assert Settings.model_config["env_file"] is None
    reset_settings_cache()
