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


def test_production_startup_fails_clearly_on_a_mistyped_role():
    """The staging/production slip: 'analyst-prod' instead of 'analyst' must stop the service at START-UP with a readable message."""
    import pytest
    bad = "k" * 24 + ":admin:acme," + "m" * 24 + ":analyst-prod:acme," + "v" * 24 + ":viewer:acme"
    with pytest.raises(ValueError) as e:
        prod(api_keys=bad)
    assert "entry #2" in str(e.value) and "analyst-prod" in str(e.value) and "admin, analyst or viewer" in str(e.value)


def test_production_startup_fails_on_wrong_shape_and_short_keys():
    import pytest
    with pytest.raises(ValueError, match="entry #1 must look like key:role:tenant"):
        prod(api_keys="k" * 24 + ":admin")
    with pytest.raises(ValueError, match="24"):
        prod(api_keys="short:admin:acme")


def test_doctor_warns_when_keys_span_different_tenants(monkeypatch, capsys):
    from app.core.config import reset_settings_cache
    from scripts import doctor
    monkeypatch.setenv("API_KEYS", "a" * 24 + ":admin:acme-bank-prod," + "b" * 24 + ":analyst:acme-bank-prod," + "c" * 24 + ":viewer:acme-bank")
    reset_settings_cache()
    doctor.main([])
    out = capsys.readouterr().out
    assert "[WARN] API key tenants" in out and "acme-bank, acme-bank-prod" in out
    reset_settings_cache()
