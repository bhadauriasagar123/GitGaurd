# Deploying on Azure with Azure DevOps (free-tier optimised)

> Pricing and free-tier terms change. Verify the numbers on the Azure/Azure DevOps pricing pages before relying on them.

## Cheapest viable topology

| Component | Choice | Cost note |
|---|---|---|
| Compute | **App Service Linux, F1** (code deploy, Python 3.12) | Free tier; ~60 CPU-min/day quota, no Always-On → fine for a demo, cold start on first hit. Use B1 for the judging window if you want it always warm. |
| PostgreSQL | **Azure Database for PostgreSQL – Flexible Server, Burstable B1ms** | Included in the *Azure free account* for 12 months (750 h + 32 GB) at the time of writing. |
| Redis | **Free managed Redis (Upstash or Redis Cloud free tier)** via `rediss://` URL | Azure Cache for Redis has no free tier. Move to Azure Managed Redis / Cache for Redis when you scale. |
| LLM (optional) | **Any OpenAI-compatible API** → `LLM_BASE_URL/LLM_API_KEY/LLM_MODEL` (free: Groq, GitHub Models, Gemini, OpenRouter), or **Azure AI Foundry** → `FOUNDRY_ENDPOINT/KEY/DEPLOYMENT` | The app runs fully without one (offline analyst) and falls back to it on any LLM error or rate limit. |
| CI/CD | **Azure DevOps Pipelines** | Free tier: 1 Microsoft-hosted parallel job (1,800 min/month) for *public* projects; **private projects must request the free grant** (form linked from Organization settings → Parallel jobs) — or use a **self-hosted agent** on your laptop/VM, which is free (swap `vmImage: ubuntu-latest` for `name: <your-pool>`). |
| Secrets | Pipeline **Library variable group** (secret variables) → Bicep secure params → App Settings | Upgrade path: Key Vault references. |

> **Starting at $0?** See [FREE_ARCHITECTURE.md](FREE_ARCHITECTURE.md) (Render + Neon + Upstash, no Azure subscription needed).

> **Agent-driven delivery:** the pipeline is now `Validate -> Staging -> Production` with review/gate/deploy agents, a pluggable deploy target (Azure App Service **or any host with a deploy hook**) and a human approval on production. The authoritative variable list and set-up steps are in [AGENTS.md](AGENTS.md); the Azure-specific steps below remain valid for `DEPLOY_TARGET=azure-webapp`.

## One-time setup (≈20 min)

1. **Azure**: create/sign in to a subscription (free account is fine). Create a resource group, e.g. `rg-regguard`.
2. **Azure DevOps**: create an Organization + Project; push this repo to **Repos** (or connect GitHub).
3. **Service connection**: Project settings → Service connections → *Azure Resource Manager* → *Workload identity federation (automatic)* scoped to `rg-regguard`. Note its name.
4. **Redis**: create a free database at Upstash/Redis Cloud, copy the `rediss://default:<password>@host:port` URL.
5. **Library → Variable group `regguard-secrets`**:

| Variable | Value | Secret |
|---|---|---|
| `AZURE_SERVICE_CONNECTION` | name from step 3 | no |
| `RESOURCE_GROUP` / `LOCATION` / `WEBAPP_NAME` | `rg-regguard` / e.g. `centralindia` / globally-unique name | no |
| `PG_ADMIN_PASSWORD` | letters+digits, 16+ chars | **yes** |
| `REDIS_URL` | from step 4 | **yes** |
| `API_KEYS` | `<24+ random>:admin:acme-bank,<24+ random>:analyst:acme-bank,<24+ random>:viewer:acme-bank` | **yes** |
| `ENC_KEY` | `python -c "import secrets;print(secrets.token_hex(32))"` | **yes** |
| `FOUNDRY_ENDPOINT` / `FOUNDRY_KEY` | optional | key: **yes** |

6. **Environment** `regguard-prod` (Pipelines → Environments): add an *Approval* check if you want a manual gate.
7. Pipelines → New pipeline → existing YAML → `azure-pipelines.yml`.

## What the pipeline does

`CI`: install → **417 tests** → **firewall quality gate** (fails on any missed attack/false positive) → bandit SAST → pip-audit CVE scan → secret scan → publish test + coverage → package.
`Deploy` (main only): Bicep (`infra/main.bicep`, idempotent: plan + web app + PostgreSQL + db) → zip deploy (Oryx installs `requirements.txt`) → smoke test against `/readyz`, which verifies **both PostgreSQL and Redis**.

The app creates its tables on first start (`create_all`). For schema evolution add Alembic migrations before the first production release.

## Manual (no pipeline) fallback

```bash
az group create -n rg-regguard -l centralindia
az deployment group create -g rg-regguard -f infra/main.bicep \
  -p appName=<unique> pgAdminPassword=<alnum> redisUrl='rediss://…' apiKeys='<k>:admin:acme-bank' encKey=<64hex>
zip -r app.zip app static requirements.txt && az webapp deploy -g rg-regguard -n <unique> --src-path app.zip --type zip
curl https://<unique>.azurewebsites.net/readyz
```

## Container option (App Service B1+ / Container Apps)

`Dockerfile` is multi-stage, non-root (uid 10001), has a HEALTHCHECK, and runs `uvicorn --workers N` (multi-process, restarts dead workers). `docker compose up --build` runs the whole stack locally (PostgreSQL 16 + Redis 7).

## LLM for the copilot (free or Azure)

**Free, no Azure subscription:** set three variables on the web service (Render → Environment):

| Provider | `LLM_BASE_URL` | `LLM_MODEL` | `LLM_API_KEY` |
|---|---|---|---|
| **Groq** (recommended: fast, free tier) | `https://api.groq.com/openai/v1` | `openai/gpt-oss-120b` (Groq retires models; list yours with `GET /models`) | console.groq.com → API Keys |
| GitHub Models | `https://models.github.ai/inference` | `openai/gpt-4o-mini` | GitHub token with `models:read` |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` | `gemini-2.0-flash` | aistudio.google.com |
| Ollama (local) | `http://localhost:11434/v1` | e.g. `llama3.1` | none |

**Azure:** deploy a chat model in Foundry and set `FOUNDRY_ENDPOINT=https://<resource>.openai.azure.com`, `FOUNDRY_KEY`, `FOUNDRY_DEPLOYMENT` (used when `LLM_BASE_URL` is empty).

Either way the model only sees firewall-cleaned, structured findings (never raw documents), its answer passes the egress guard, and if it times out, is rate-limited or errors, the copilot answers from the offline analyst and labels the answer `offline-fallback`. `python -m scripts.doctor` sends a one-word test prompt and reports whether the model answers. To let a model *propose* obligations/mappings, add another `LLMProvider` call inside `cqrs/handlers.ingest` **after** the firewall step and validate its output with the deterministic engine.

## Troubleshooting

* `readyz` degraded → check `checks` (postgres/redis); verify `?ssl=require` on `DATABASE_URL` and the Postgres firewall rule.
* App refuses to start in production → read the validation message (default/missing keys, SQLite, fakeredis are rejected on purpose).
* F1 cold start slow / 503 right after deploy → wait for Oryx build (first deploy ≈ 3–5 min).
