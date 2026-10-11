# Step-by-step set-up (free): local first → Neon + Upstash → CI/CD → hosted

Every step ends with a **✔ check** — do not continue until it passes. Commands are for **Windows PowerShell** (macOS/Linux: same commands, `source .venv/bin/activate`). Account creation and pasting credentials are yours to do; everything else is scripted and was rehearsed against real PostgreSQL + a Redis server.

> Third-party sites change their screens; the menu names below are indicative. What matters are the **three URLs** (PostgreSQL, Redis, deploy hook) and the **four secrets**.

## 0 · Prerequisites (5 min)
* **Python 3.12** (`python --version`), **Git** (`git --version`). Node is optional.
* Clone/open the project folder, then:
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```
✔ `pytest -q -x` → all green (≈ 45 s). *(Uses SQLite + in-process Redis, no accounts needed.)*

## 1 · Run it locally with zero accounts (2 min)
```powershell
uvicorn app.main:app --reload --no-server-header
```
Open http://localhost:8000 → the demo key is pre-filled → **Load demo dataset**.
✔ You see the donut with **75.7 %**; hover it for the breakdown; **Upload** → “poisoned circular” is blocked.
*(Dev mode keeps data in a local SQLite file `regguard.db` and uses in-process Redis. Stop with Ctrl+C.)*

## 2 · Create your secrets and `.env` (1 min)
```powershell
python -m scripts.gen_secrets --write
```
It prints three API keys (admin / analyst / viewer) and writes `.env` (git-ignored, never overwritten). **Copy `ENC_KEY` somewhere safe** — encrypted documents cannot be read without it.
✔ `python -m scripts.doctor` → `READY` (warnings about empty DATABASE_URL/REDIS_URL are expected for now).

## 3 · PostgreSQL on Neon (5 min, free)
1. Sign up at **neon.tech** → *Create project* (region near you, Postgres 16).
2. *Connection details* → tick **Pooled connection** → copy the string. It looks like
   `postgresql://user:pass@ep-xxxx-pooler.<region>.aws.neon.tech/neondb?sslmode=require`
3. Paste it into `.env` as `DATABASE_URL=` (as-is — the app converts it to the driver format and detects the pooler).

✔ `python -m scripts.doctor --init-db` → `[PASS] PostgreSQL connection … TLS on` and `[PASS] Schema`.
*If it fails:* the first connection after idle can take ~10 s (Neon wakes up) — run it again; make sure you copied the password and kept `?sslmode=require`.

## 4 · Redis on Upstash (3 min, free)
1. Sign up at **upstash.com** → *Create database* (Redis, same region, TLS on).
2. Copy the **`rediss://default:<password>@<host>.upstash.io:6379`** URL (note the double **s**).
3. Paste it into `.env` as `REDIS_URL=`.

✔ `python -m scripts.doctor` → `[PASS] Redis operations … PING + SET NX EX + GET + INCR ok`.

## 5 · Run the whole app locally on the real services (2 min)
```powershell
uvicorn app.main:app --no-server-header
python -m scripts.doctor --url http://localhost:8000
```
✔ doctor prints `READY` (healthz/readyz up, security headers present). Open the UI, paste the **analyst** key into the header, **Connect**, **Load demo dataset**.
Optional full black-box check (37 checks, loads demo data into the analyst's tenant):
```powershell
$env:BASE="http://localhost:8000"; $env:ADMIN_KEY="<admin key>"; $env:ANALYST_KEY="<analyst key>"; $env:VIEWER_KEY="<viewer key>"
python -m scripts.prod_smoke
```
✔ `37/37 checks passed`. *(To rehearse production behaviour locally set `ENV=production` and `DOCS_ENABLED=false` in `.env`; the check “Swagger hidden” expects that.)*

## 6 · Put the code in a repository (5 min)
Pick **one** (both pipelines are in the repo; use Azure DevOps if you want it, GitHub if you want zero wait):

**A. Azure DevOps (free, no Azure subscription needed)**
1. **dev.azure.com** → sign in → *New organization* → *New project* (Private).
2. *Repos* → copy the clone URL → in the project folder:
```powershell
git remote add origin <clone-url>
git push -u origin main
git checkout -b develop; git push -u origin develop; git checkout main
```
3. *Pipelines → Create Pipeline → Azure Repos Git → Existing YAML → `/azure-pipelines.yml`* (first run will ask for permissions — allow).
4. **Free build minutes:** *Organization settings → Parallel jobs* — if “Microsoft-hosted: 0”, request the free grant (form linked there; takes a few business days) **or** use the GitHub option below meanwhile.

**B. GitHub (no waiting)**: create a private repo, `git remote add origin <url>`, `git push -u origin main`, push `develop` too. `.github/workflows/ci.yml` runs automatically. *Settings → Environments*: create `staging` and `production` (add **Required reviewers** on production).

✔ The first run goes green on: *pipeline/PR review agents*, *build + tests*, *integration tests on real PostgreSQL 16 + Redis 7*.

## 7 · Host the app free on Render (10 min)
1. **render.com** → *New → Blueprint* → connect the repo (reads `render.yaml`) → when asked, enter **DATABASE_URL** and **REDIS_URL** (from steps 3–4), **API_KEYS** and **ENC_KEY** (from `.env` — use the **same** `ENC_KEY` only if you want to reuse the same Neon data; for a separate staging/production use new keys).
2. Wait for the first build (3–5 min).
✔ `python -m scripts.doctor --url https://<service>.onrender.com` → `READY`, then run `prod_smoke` against that URL (step 5 command with `BASE=https://…`).

## 8 · Staging + production wiring (10 min)
Create **two** Render services (staging from branch `develop`, production from `main`), each with **its own** Neon database/branch, Upstash database and API keys. In each service: *Settings → Deploy Hook* → copy URL. Turn **Auto-Deploy off** so the pipeline controls releases.

| Variable / secret | Value |
|---|---|
| *(no DEPLOY_TARGET variable needed)* | The pipeline defaults to the free `webhook` target through a compile-time parameter `deployTarget`; only choose `azure-webapp` (and give `azureServiceConnection`) when you have an Azure subscription. |
| `STAGING_URL`, `PROD_URL` | the two `https://…onrender.com` URLs |
| `STAGING_DEPLOY_HOOK_URL`, `PROD_DEPLOY_HOOK_URL` | the two deploy hooks |
| `STAGING_API_KEYS`, `PROD_API_KEYS` | each service's `API_KEYS` string (`key:role:tenant,…`) |

Azure DevOps: *Pipelines → Library → Variable group `regguard-secrets`* (lock the secrets) and *Pipelines → Environments*: `regguard-staging`, `regguard-prod` (add **Approvals** on prod). GitHub: add the same names as repository **secrets**.
✔ Push to `develop` → pipeline deploys staging → smoke suite passes. Merge `develop` → `main` → Release Gate says GO → you approve → production deploys → smoke passes.

## 9 · Day-to-day
```powershell
git checkout -b feature/my-change      # work, commit
python -m scripts.ci_agents pr-review --base develop   # local preview of the PR agent
git push -u origin feature/my-change   # open a PR into develop: agents review it and comment
```
Add **branch policies** on `main`/`develop`: require the pipeline (Azure DevOps *Build validation*) or the `ci-cd` checks (GitHub *branch protection*), a reviewer, and resolved comments. Details in [AGENTS.md](AGENTS.md).

## Troubleshooting

| Symptom | Likely cause → fix |
|---|---|
| `doctor`: `PostgreSQL connection … timeout` | Neon is waking up → run again. Check password / region; keep `?sslmode=require`. |
| `doctor`: `Redis connection … ` | Upstash URL must start with `rediss://` (two s) and include the password. |
| App starts then `503` on `/readyz` | `checks` in the JSON names the dependency that is down. |
| `Settings … validation error` in production | A required secret is missing/short: `API_KEYS` (≥ 24 chars/key), `ENC_KEY` (64 hex), real Redis, PostgreSQL. |
| Documents unreadable after redeploy | `ENC_KEY` changed. Restore the old value (that is why you keep a copy). |
| `429 Too Many Requests` during demos | Per-key rate limit (240/min general, 40/min heavy). Wait `Retry-After` seconds or raise `RATE_LIMIT*`. |
| First request very slow on Render free | The service was asleep — normal; ping `/healthz` before a demo or use an always-on plan. |
| Pipeline queued forever (Azure DevOps) | No free hosted parallelism yet → request the grant or use the GitHub workflow. |
| Upstash “max daily commands” | Free quota used (each request uses a few commands) → avoid load tests or upgrade. |
| `pip install` slow/ fails on Windows | Use Python 3.12 (not 3.13+) and an activated venv. |

## What was and was not verified
Rehearsed end-to-end on this machine with real PostgreSQL 16 and a Redis-protocol server: secrets → `.env` → doctor → schema → Alembic → app started from `.env` only → 37/37 smoke → full test suite against those services (the same thing the CI *integration* job does). **Not exercised** against Neon, Upstash, Render, Azure DevOps or GitHub themselves — the doctor and smoke suite exist so the first real run tells you exactly what differs.
