"""The set-up tools a first-time user depends on: secret generation and the doctor preflight."""
import re

import pytest

from app.core.config import reset_settings_cache
from scripts import doctor, gen_secrets


def test_gen_secrets_values_are_strong_and_well_formed():
    vals, text = gen_secrets.build("production", "acme-bank")
    assert re.fullmatch(r"[0-9a-f]{64}", vals["ENC_KEY"])
    entries = vals["API_KEYS"].split(",")
    assert {e.split(":")[1] for e in entries} == {"admin", "analyst", "viewer"} and all(len(e.split(":")[0]) >= 24 for e in entries)
    assert len({e.split(":")[0] for e in entries}) == 3  # distinct keys
    assert "DOCS_ENABLED=false" in text and "ENV=production" in text
    assert gen_secrets.build("production", "t")[0]["ENC_KEY"] != vals["ENC_KEY"]  # fresh randomness every time


def test_gen_secrets_never_overwrites_existing_env(tmp_path, capsys):
    target = tmp_path / ".env"
    assert gen_secrets.main(["--write", str(target)]) == 0 and target.exists()
    first = target.read_text()
    assert gen_secrets.main(["--write", str(target)]) == 1 and target.read_text() == first  # protects the ENC_KEY
    assert gen_secrets.main(["--write", str(target), "--force"]) == 0 and target.read_text() != first


def test_generated_env_file_loads_into_settings(tmp_path, monkeypatch):
    from app.core.config import Settings
    p = tmp_path / ".env"
    gen_secrets.main(["--write", str(p), "--env", "production"])
    text = p.read_text().replace("DATABASE_URL=\n", "DATABASE_URL=postgres://u:p@ep-x-pooler.neon.tech/db?sslmode=require\n").replace("REDIS_URL=\n", "REDIS_URL=rediss://default:pw@h.upstash.io:6379\n")
    p.write_text(text)
    for k in ("ENV", "DATABASE_URL", "REDIS_URL", "API_KEYS", "ENC_KEY", "DOCS_ENABLED"):
        monkeypatch.delenv(k, raising=False)
    s = Settings(_env_file=str(p))
    assert s.is_prod and s.database_url.startswith("postgresql+asyncpg://") and len(s.key_ring()) == 3


def test_doctor_passes_on_a_healthy_dev_setup(capsys):
    rc = doctor.main(["--init-db"])
    out = capsys.readouterr().out
    assert rc == 0 and "READY" in out and "Redis operations" in out and "Schema" in out


def test_doctor_fails_loudly_with_hints_when_redis_is_unreachable(monkeypatch, capsys):
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")  # nothing listens on port 1
    reset_settings_cache()
    from app.infra import redis_client
    redis_client._client = None
    rc = doctor.main([])
    out = capsys.readouterr().out
    assert rc == 1 and "[FAIL] Redis connection" in out and "rediss://" in out
    redis_client._client = None


def test_doctor_rejects_unsafe_production_config(monkeypatch, capsys):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("API_KEYS", "")
    reset_settings_cache()
    rc = doctor.main([])
    out = capsys.readouterr().out
    assert rc == 1 and "[FAIL] Settings" in out
    reset_settings_cache()


def test_doctor_never_prints_secrets(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    doctor.main([])
    out = capsys.readouterr().out
    assert "admin-key-0000000000000001" not in out and "mask" not in out.lower()
    assert doctor.mask("postgresql://user:SuperSecret@host/db") == "postgresql://user:***@host/db"


def test_smoke_accepts_one_api_keys_string_and_warns_on_truncated_keys(monkeypatch, capsys):
    import importlib
    import sys
    for k in ("ADMIN_KEY", "ANALYST_KEY", "VIEWER_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("API_KEYS", "A" * 32 + ":admin:t," + "B" * 32 + ":analyst:t," + "C" * 31 + ":viewer:t")
    sys.modules.pop("scripts.prod_smoke", None)
    smoke = importlib.import_module("scripts.prod_smoke")
    assert smoke.K == {"admin": "A" * 32, "analyst": "B" * 32, "viewer": "C" * 31}
    assert "viewer key is only 31 characters" in capsys.readouterr().out   # the exact mistake that caused the 401 on staging
    sys.modules.pop("scripts.prod_smoke", None)
