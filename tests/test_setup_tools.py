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
    out = capsys.readouterr().out                                          # the exact mistake that caused the 401 on staging
    assert "the viewer key is 31 characters but the others are 32" in out and "probably truncated" in out
    assert "admin key is" not in out and "analyst key is" not in out
    sys.modules.pop("scripts.prod_smoke", None)


def _load_smoke(monkeypatch, argv=()):
    import importlib
    import sys
    monkeypatch.setattr(sys, "argv", ["prod_smoke", *argv])
    sys.modules.pop("scripts.prod_smoke", None)
    mod = importlib.import_module("scripts.prod_smoke")
    sys.modules.pop("scripts.prod_smoke", None)
    return mod


def test_smoke_api_keys_override_stale_individual_variables(monkeypatch, capsys):
    """The staging mix-up: old ADMIN_KEY/ANALYST_KEY/VIEWER_KEY left in the shell must NOT beat a freshly supplied API_KEYS."""
    monkeypatch.setenv("ADMIN_KEY", "OLD" + "x" * 28)
    monkeypatch.setenv("ANALYST_KEY", "OLD" + "y" * 29)
    monkeypatch.setenv("VIEWER_KEY", "OLD" + "z" * 29)
    monkeypatch.setenv("API_KEYS", "N" * 32 + ":admin:t," + "M" * 32 + ":analyst:t," + "L" * 32 + ":viewer:t")
    smoke = _load_smoke(monkeypatch)
    assert smoke.K == {"admin": "N" * 32, "analyst": "M" * 32, "viewer": "L" * 32}
    out = capsys.readouterr().out
    assert "individual *_KEY variables are ignored" in out and "WARNING" not in out


def test_smoke_reads_keys_from_an_env_file_without_printing_them(monkeypatch, capsys, tmp_path):
    f = tmp_path / ".env.staging"
    f.write_text("ENV=production\nAPI_KEYS=" + "a" * 32 + ":admin:t," + "b" * 32 + ":analyst:t," + "c" * 32 + ":viewer:t\nENC_KEY=" + "0" * 64 + "\n")
    monkeypatch.delenv("API_KEYS", raising=False)
    smoke = _load_smoke(monkeypatch, ["--env-file", str(f)])
    assert smoke.K["admin"] == "a" * 32 and smoke.K["viewer"] == "c" * 32
    out = capsys.readouterr().out
    assert "a" * 32 not in out and "0" * 64 not in out and str(f) in out


def test_gen_secrets_does_not_print_keys_by_default(tmp_path, capsys):
    target = tmp_path / ".env.staging"
    assert gen_secrets.main(["--write", str(target)]) == 0
    out = capsys.readouterr().out
    keys = [e.split(":")[0] for e in [l for l in target.read_text().splitlines() if l.startswith("API_KEYS=")][0][9:].split(",")]
    assert all(k not in out for k in keys) and "not printed" in out
    t2 = tmp_path / ".env.other"
    gen_secrets.main(["--write", str(t2), "--show"])
    shown = capsys.readouterr().out
    assert any(k in shown for k in [e.split(":")[0] for e in [l for l in t2.read_text().splitlines() if l.startswith("API_KEYS=")][0][9:].split(",")])


def test_gitignore_covers_every_env_variant():
    ig = open(".gitignore", encoding="utf8").read().splitlines()
    assert ".env" in ig and ".env.*" in ig and "!.env.example" in ig


async def test_smoke_stops_early_with_a_clear_message_when_keys_do_not_match(client, monkeypatch, capsys, tmp_path):
    """The staging confusion: keys from another environment must produce ONE clear explanation, not a traceback.
    Runs in-process against the test app (same event loop, no threads, no sockets) so it cannot disturb other tests."""
    import importlib
    import sys

    import httpx
    wrong = tmp_path / "wrong.env"
    wrong.write_text("API_KEYS=" + "z" * 32 + ":admin:t," + "y" * 32 + ":analyst:t," + "x" * 32 + ":viewer:t")
    app = client._transport.app
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.ASGITransport(app=app), base_url="http://svc", timeout=30))
    monkeypatch.setenv("BASE", "http://svc")
    monkeypatch.setattr(sys, "argv", ["prod_smoke", "--env-file", str(wrong)])
    sys.modules.pop("scripts.prod_smoke", None)
    smoke = importlib.import_module("scripts.prod_smoke")
    rc = await smoke.main()
    sys.modules.pop("scripts.prod_smoke", None)
    out = capsys.readouterr().out
    assert rc == 2 and "STOPPED: the keys you supplied do not match" in out and "rejected by the service (HTTP 401)" in out
    assert "Traceback" not in out and "KeyError" not in out
