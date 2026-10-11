"""Preflight / "doctor": verifies configuration and every dependency BEFORE you start (or deploy) the app.

    python -m scripts.doctor                     # check .env / environment: settings, secrets, PostgreSQL, Redis
    python -m scripts.doctor --init-db           # additionally create the tables (safe to repeat)
    python -m scripts.doctor --url https://my-app.onrender.com    # also probe a running deployment (/healthz, /readyz)

Reads the same variables as the app (.env is loaded). Exit code 1 if any check FAILS. Secrets are never printed."""
import argparse
import asyncio
import re
import sys
import time

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
rows: list[tuple[str, str, str]] = []


def add(status: str, name: str, detail: str = "", hint: str = "") -> None:
    rows.append((status, name, detail + (f"\n         -> {hint}" if hint and status != PASS else "")))


def mask(url: str) -> str:
    return re.sub(r"(://[^:/@]+:)[^@]+@", r"\1***@", url)


async def run(args) -> int:
    add(PASS if sys.version_info >= (3, 11) else FAIL, "Python version", sys.version.split()[0], "Install Python 3.12 (python.org or winget install Python.Python.3.12)")
    try:
        from app.core.config import get_settings
        s = get_settings()
    except Exception as e:  # noqa: BLE001 - pydantic ValidationError / ValueError
        add(FAIL, "Settings", str(e).replace("\n", " ")[:300], "Fix the variable named above in .env (see .env.example); in production every secret is mandatory")
        return report()
    add(PASS, "Settings load", f"ENV={s.env}")

    # ---- secrets
    try:
        ring = s.key_ring()
        roles = sorted({k["role"] for k in ring})
        add(PASS if {"admin", "analyst", "viewer"} <= set(roles) else WARN, "API keys", f"{len(ring)} key(s), roles: {', '.join(roles)}",
            "Define admin, analyst and viewer keys: API_KEYS=k1:admin:tenant,k2:analyst:tenant,k3:viewer:tenant")
        if not s.api_keys:
            add(WARN, "API_KEYS not set", "using the built-in demo key (dev only)", "python -m scripts.gen_secrets --write")
    except ValueError as e:
        add(FAIL, "API keys", str(e), "Format is key:role:tenant (role = admin|analyst|viewer); keys >= 24 chars in production")
    try:
        from app.core import crypto
        ok = crypto.decrypt(crypto.encrypt("probe", "doctor:1"), "doctor:1") == "probe"
        add(PASS if ok and s.enc_key else WARN, "Encryption key", "AES-256-GCM round-trip OK" if s.enc_key else "derived dev key in use",
            "Generate one: python -m scripts.gen_secrets   (keep a copy - data cannot be decrypted without it)")
    except Exception as e:  # noqa: BLE001
        add(FAIL, "Encryption key", f"{type(e).__name__}: {e}", "ENC_KEY must be exactly 64 hex characters")

    # ---- PostgreSQL
    from sqlalchemy import text
    from app.infra.db import Database
    db = Database.instance()
    dialect = db.engine.dialect.name
    add(PASS, "Database target", f"{dialect}  {mask(s.database_url)}" + ("  (pooler detected)" if s.uses_pgbouncer else ""))
    if dialect == "sqlite" and s.is_prod:
        add(FAIL, "Database", "SQLite in production", "Set DATABASE_URL to PostgreSQL (Neon)")
    else:
        try:
            t0 = time.perf_counter()
            async with db.engine.connect() as c:
                if dialect == "postgresql":
                    ver = (await c.execute(text("select version()"))).scalar_one().split(",")[0]
                    try:
                        ssl = (await c.execute(text("select ssl from pg_stat_ssl where pid = pg_backend_pid()"))).scalar()
                    except Exception:  # noqa: BLE001 - view not visible on some managed services
                        ssl = None
                    add(PASS, "PostgreSQL connection", f"{ver} - {1000 * (time.perf_counter() - t0):.0f} ms - TLS {'on' if ssl else 'unknown/off'}")
                    if ssl is False and s.is_prod:
                        add(WARN, "PostgreSQL TLS", "connection is not encrypted", "Add ?sslmode=require to DATABASE_URL")
                else:
                    await c.execute(text("select 1"))
                    add(PASS, "SQLite connection", "ok (local dev only)")
            if args.init_db:
                await db.create_schema()
                add(PASS, "Schema", "tables created / already present")
            else:
                async with db.engine.connect() as c:
                    tables = await c.run_sync(lambda conn: __import__("sqlalchemy").inspect(conn).get_table_names())
                missing = {"documents", "audit_log", "doc_store"} - set(tables)
                add(PASS if not missing else WARN, "Schema", "present" if not missing else f"missing tables: {sorted(missing)}",
                    "They are created automatically at app start-up, or run: python -m scripts.doctor --init-db")
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {str(e)[:200]}"
            hint = "Check the URL/password; for Neon use the *pooled* string and keep ?sslmode=require; the first connection after idle can take ~10 s - retry"
            add(FAIL, "PostgreSQL connection", msg, hint)

    # ---- Redis
    from app.infra.redis_client import close_redis, get_redis
    fake = s.redis_url.startswith("fakeredis") or not s.redis_url
    if fake:
        add(FAIL if s.is_prod else WARN, "Redis target", "in-process fakeredis (not shared between processes, lost on restart)",
            "Set REDIS_URL=rediss://default:<password>@<host>:6379 (Upstash) for real use")
    else:
        add(PASS, "Redis target", mask(s.redis_url))
    try:
        r = await get_redis()
        t0 = time.perf_counter()
        await r.ping()
        ms = 1000 * (time.perf_counter() - t0)
        key = f"doctor:{int(time.time())}"
        ok = await r.set(key, "1", nx=True, ex=30) and await r.get(key) == "1" and await r.incr(key + ":n") == 1
        await r.delete(key, key + ":n")
        ver = ""
        try:
            ver = " - redis " + (await r.info("server")).get("redis_version", "?")
        except Exception:  # noqa: BLE001
            pass
        add(PASS if ok else FAIL, "Redis operations", f"PING + SET NX EX + GET + INCR ok - {ms:.0f} ms{ver} - connection cap: {s.redis_max_connections} per process", "Check REDIS_URL (rediss:// for TLS) and the password")
    except Exception as e:  # noqa: BLE001
        add(FAIL, "Redis connection", f"{type(e).__name__}: {str(e)[:200]}", "Check REDIS_URL; Upstash needs rediss:// (two s) and the database password")
    await close_redis()
    await Database.dispose()

    # ---- optional: a running deployment
    if args.url:
        import httpx
        base = args.url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=45) as c:
                h = await c.get(f"{base}/healthz")
                add(PASS if h.status_code == 200 else FAIL, f"{base}/healthz", f"HTTP {h.status_code}", "Service not up yet? On free hosts the first request wakes it - retry in ~30 s")
                rd = await c.get(f"{base}/readyz")
                add(PASS if rd.status_code == 200 else FAIL, f"{base}/readyz", rd.text[:160], "readyz shows which dependency is down (postgres / redis)")
                docs = await c.get(f"{base}/docs")
                add(PASS if docs.status_code == 404 else WARN, "Swagger hidden", f"/docs -> {docs.status_code}", "Set DOCS_ENABLED=false in production")
                hdr = h.headers
                good = hdr.get("x-content-type-options") == "nosniff" and "frame-ancestors" in hdr.get("content-security-policy", "") and "server" not in hdr
                add(PASS if good else WARN, "Security headers", "present" if good else "missing/leaky", "Use `--no-server-header` when starting uvicorn (Dockerfile already does)")
        except Exception as e:  # noqa: BLE001
            add(FAIL, "Deployment probe", f"{type(e).__name__}: {e}", "Is the URL right and the service running?")
    return report()


def report() -> int:
    width = max(len(n) for _, n, _ in rows)
    for st, name, detail in rows:
        print(f"[{st}] {name.ljust(width)}  {detail}")
    fails = sum(1 for st, _, _ in rows if st == FAIL)
    warns = sum(1 for st, _, _ in rows if st == WARN)
    print(f"\n{len(rows) - fails - warns} passed, {warns} warning(s), {fails} failed" + ("  ->  READY" if not fails else "  ->  fix the FAIL lines above and re-run"))
    return 1 if fails else 0


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--init-db", action="store_true")
    ap.add_argument("--url")
    rows.clear()
    return asyncio.run(run(ap.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
