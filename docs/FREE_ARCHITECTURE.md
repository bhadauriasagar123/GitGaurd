# Free ($0) starter architecture

Goal: run the whole product, with PostgreSQL and Redis, for **$0** while you build and demo — and move to Azure later **without changing code** (only environment variables).

```
                    HTTPS (provided by the host)
 Browser / API  ───────────────────────────────►  Render free web service  (Docker image of this repo, 1 worker)
                                                      │            │
                                          DATABASE_URL │            │ REDIS_URL
                                                      ▼            ▼
                                        Neon free PostgreSQL   Upstash free Redis
                                        (tables + JSONB)       (idempotency, rate limits, read-model cache,
                                                                firewall session memory, locks)

 CI/CD: Azure DevOps Pipelines (free org, no Azure subscription) ──► deploy hook ──► Render      (see AGENTS.md)
```

| Layer | Free choice | Why it fits | Watch out for (verify current terms) |
|---|---|---|---|
| App hosting | **Render** free web service (Docker) | HTTPS + auto-deploy + health checks, no card needed for the free plan | sleeps after idle (first request slow); small RAM/CPU → `WEB_CONCURRENCY=1` |
| PostgreSQL | **Neon** free | real PostgreSQL 16, JSONB, no expiry on the free tier | scales to zero (first query after idle takes a moment — the app waits up to 30 s); uses a pooler, which the app detects automatically |
| Redis | **Upstash** free | TLS `rediss://`, serverless; the app uses **one** connection per process (`REDIS_MAX_CONNECTIONS=1`, commands queue on it) | daily command quota — each API request uses a few commands; fine for dev/demo, not for load tests |
| CI/CD | **Azure DevOps Pipelines** (or GitHub Actions) | pipeline + agents already written | private projects need the free-parallelism request, or use a self-hosted agent |
| LLM (optional) | none (built-in deterministic analyst) | zero cost, no hallucination | add Azure AI Foundry later for richer answers |
| Secrets | host environment variables | never in git (`render.yaml` marks them `sync:false`) | rotate if leaked; no Key Vault yet |

Total cost: **$0**. Nothing in the app is tied to these vendors — they are only three URLs.

## Set-up (≈15 minutes)

1. **Neon** → create project → copy the connection string (the *pooled* one). Paste it as-is: `postgresql://user:pass@ep-…-pooler….neon.tech/db?sslmode=require`. The app converts it to the asyncpg form automatically (`postgresql+asyncpg://…?ssl=require`) and disables prepared-statement caching for poolers.
2. **Upstash** → create Redis database → copy the `rediss://default:<password>@<host>:6379` URL.
3. Generate secrets locally:
   ```bash
   python -c "import secrets;print(secrets.token_hex(32))"        # ENC_KEY (64 hex chars) - keep a copy: data cannot be decrypted without it
   python -c "import secrets;print(secrets.token_urlsafe(24))"   # run 3x for the admin / analyst / viewer API keys
   ```
   `API_KEYS=<k1>:admin:acme-bank,<k2>:analyst:acme-bank,<k3>:viewer:acme-bank`
4. **Render** → New → **Blueprint** → pick this repo (it reads `render.yaml`) → paste `DATABASE_URL`, `REDIS_URL`, `API_KEYS`, `ENC_KEY` when prompted.
5. Wait for the first build (~3–5 min), then check `https://<service>.onrender.com/readyz` → `{"status":"ready","checks":{"postgres":"up","redis":"up"}}`.
6. Verify end to end with the black-box suite (it loads the demo dataset into the tenant of the analyst key):
   ```bash
   BASE=https://<service>.onrender.com ADMIN_KEY=<k1> ANALYST_KEY=<k2> VIEWER_KEY=<k3> python -m scripts.prod_smoke
   ```
7. Open the site, paste the *viewer* or *analyst* key into the header, press **Connect**.

Wire the pipeline later: Render → service → Settings → **Deploy Hook** → store it as `STAGING_DEPLOY_HOOK_URL` / `PROD_DEPLOY_HOOK_URL` and set `DEPLOY_TARGET=webhook` in the Azure DevOps variable group. For staging + production use **two** Render services (two blueprints, e.g. branches `develop` and `main`) with **separate** Neon branches/databases, Upstash databases and API keys.

## What this setup does NOT give you (be upfront)

* **No always-on guarantee** — free web services sleep. For the judging window, upgrade the service to the cheapest always-on plan or ping `/healthz` shortly before the demo.
* **No private networking, WAF or SSO** — keys protect the API; add Front Door/WAF and Entra ID when you move to Azure.
* **Backups** — rely on Neon's point-in-time history (check its free-tier retention) and keep a copy of `ENC_KEY` somewhere safe.
* **Not yet exercised against Neon/Upstash/Render themselves** — the URL handling is unit-tested and the app is proven on real PostgreSQL + a Redis-protocol server, but run the smoke suite (step 6) after the first deploy.

## Moving to Azure later (no code change)

Set the same variables on App Service and point them at Azure Database for PostgreSQL / a managed Redis; `infra/main.bicep` and the pipeline's `DEPLOY_TARGET=azure-webapp` path already do this. Nothing else changes.
