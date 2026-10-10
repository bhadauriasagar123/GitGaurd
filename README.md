# RegGuard Shield

**ET AI Hackathon – Agentic Edition · Problem 1 (Banking Regulatory Compliance) + Problem 2 (Prompt Injection Firewall) as one monolith.**

Problem 1 is the product: an agentic system that turns regulations into obligations, maps them to a bank's controls, tests them against evidence, finds and prioritises gaps and recommends fixes.
Problem 2 is the shield: *every* byte of external content (regulatory PDFs, circulars, e-mails, control spreadsheets, evidence feeds, user questions) must pass the **Prompt Injection Firewall** before any agent sees it, and every model answer must pass the **Egress Guard**, so nobody can use the AI to extract the agent's prompt or the bank's confidential documents.

```
untrusted input ─▶ [Firewall: extract▸normalise▸decode▸detect▸session▸sanitise] ─▶ agents ─▶ [Egress guard] ─▶ response
                              │ block                                                            │ withhold/redact
                              ▼                                                                  ▼
                   quarantine (hash only) + audit                                    audit + canary alarm
```

**Stack:** Python 3.12 · FastAPI · PostgreSQL (relational tables **+ JSONB document collections**) · Redis · Azure App Service / Azure DevOps · optional Azure AI Foundry model.

## Run it (2 minutes)

```bash
python -m venv .venv && .venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --no-server-header                            # http://localhost:8000  (dev key is pre-filled in the UI)
pytest -q                                                # 335 tests
python -m scripts.eval_firewall                          # firewall regression corpus
python -m scripts.eval_accuracy all                      # gold-set accuracy (extraction / mapping / firewall)
```

Dev mode uses SQLite + in-process Redis so it starts with zero services. For the real stack: `docker compose up --build` (PostgreSQL 16 + Redis 7 + app), or point `DATABASE_URL` / `REDIS_URL` at managed services (see `.env.example`). The same test-suite also passes against a real PostgreSQL (`DATABASE_URL=postgresql+asyncpg://… pytest`).

Open the UI → **Load demo dataset** → walk the tabs. Swagger is at `/docs` (disabled in production).

## Problem 1 – all 14 desirable features

| # | Feature | Where | Visible via |
|---|---|---|---|
| 1 | Regulatory intelligence & knowledge ingestion | `compliance/obligations.py`, `cqrs/handlers.py`, `firewall/extract.py` (PDF, DOCX, HTML, MD, e-mail, JSON, OCR) | `POST /api/v1/documents` |
| 2 | Regulatory change intelligence | `compliance/changes.py` (clause-aligned version diff, materiality) | `GET /changes`, UI *Reg. Change* |
| 3 | Obligation extraction | modality (mandatory / prohibited / recommended), actor, deadlines, frequencies, retention, penalty, severity | `GET /obligations` |
| 4 | Control-framework understanding | `compliance/controls.py` (text blocks or JSON → type, owner, cadence, automation, SLAs) | `GET /controls` |
| 5 | Regulation → control mapping | TF-IDF cosine + topic taxonomy, explainable rationale | `GET /assessments` |
| 6 | Control effectiveness | design × operating (freshness, pass-rate, exceptions) | `GET /controls` |
| 7 | Evidence-based compliance | untested/stale controls can never be "compliant" | `GET /assessments` |
| 8 | Gap identification | 7 gap types: no control, weak coverage, ineffective, untested, stale, threshold mismatch, frequency mismatch | `GET /gaps` |
| 9 | Risk-based prioritisation | severity × likelihood × urgency with visible factors | `GET /gaps?minBand=high` |
| 10 | Remediation engine | steps, owner, effort, target days, success criteria, expected score uplift | inside each gap |
| 11 | Autonomous impact analysis | ingesting a new regulation version triggers diff + re-assessment + impact report, no human action | `GET /impact` |
| 12 | What-if / simulation | pure re-analysis of modified state (add/remove/update control, add evidence, regulator changes threshold) | `POST /whatif` |
| 13 | Cross-regulation intelligence | clusters overlapping obligations across regulators, proposes one harmonised control | `GET /cross-regulation` |
| 14 | Contradiction detection | hard numeric conflicts (e.g. AML retain ≥5y vs GDPR-style ≤12m), modality conflicts, deadline divergence | `GET /contradictions` |

Plus the full chain *regulation → obligation → applicability → control → evidence → test → gap → remediation → monitoring* at `GET /trace/{obligationId}` and `GET /monitoring/trend`.

## Problem 2 – all 9 attack classes

Instruction Override · Role Change · Secret Extraction · Tool Abuse · Credential Theft · Context Poisoning · Multi-Step Jailbreak (session memory in Redis) · Encoded Instructions (base64/hex/URL/unicode/entities/binary/ROT13/reversed/leet/zero-width/homoglyph/tag characters, decoded recursively) · Indirect Injection (hidden CSS text, comments, alt/aria text, metadata, `w:vanish` Word runs, PDF annotations, code comments).
Input sources: user message, web, HTML, PDF, e-mail, Markdown, Word, API JSON, OCR text, source code, image-via-OCR text.

Two layers: explainable **rules** (precise, per-class evidence) plus a small **learned intent model** (generalises across paraphrase and languages; pure-Python inference, no extra runtime dependencies). Measured on an unseen, one-shot gold set (`python -m scripts.eval_accuracy v4`): **88 % accuracy, 78 % attack recall, 0 % false positives**; extraction F1 100 %, control-mapping top-1 80 %. The dev regression corpus (`scripts.eval_firewall`) is 52/52 attacks, 0/20 false positives, ~3 ms per scan. **Read [docs/ACCURACY.md](docs/ACCURACY.md) before quoting numbers**: the sets are small and authored by the team, rules alone scored only 22 % on unseen phrasing before the learned layer was added, and a determined adaptive attacker can still evade any classifier. Defence in depth (spotlighting, least-privilege agents, egress guard, canaries, audit) limits the blast radius.

## Protecting *"my prompt and my files"*

1. Documents are **AES-256-GCM encrypted at rest**, bound to `tenant:docId` (copying ciphertext across tenants fails to decrypt).
2. No API returns document text; `?reveal=true` is **admin-only and audited**.
3. The LLM never receives raw documents — only structured findings wrapped with a random **spotlight** boundary.
4. **Prompt Vault + canary tokens**: the system prompt is fingerprinted and carries a canary; the **Egress Guard** withholds any answer containing the canary, prompt n-grams, bulk (>30 words) verbatim document text, secrets, or exfiltration URLs.
5. Poisoned uploads are **blocked + quarantined (hash only)**; repeated attempts raise session risk.

## Engineering features judges look for

Idempotency (`Idempotency-Key`: replay, payload-mismatch 422, in-flight 409, failure releases key) · correlation IDs (validated, propagated through logs/audit/agent trace/errors) · RFC-7807 error model with no internal leakage · RBAC + tenant isolation · Redis rate limiting · tamper-evident hash-chained audit log · CQRS with Redis read-model · distributed locks · health/readiness probes · structured JSON logs with redaction · agent execution trace on every ingest.

Delivery agents: [AGENTS](docs/AGENTS.md) · Accuracy: [ACCURACY](docs/ACCURACY.md) · Tests: [TEST_CASES](docs/TEST_CASES.md) · [TEST_REPORT](docs/TEST_REPORT.md) · Docs: [ARCHITECTURE](docs/ARCHITECTURE.md) · [SECURITY / VAPT](docs/SECURITY.md) · [DEPLOYMENT on Azure DevOps](docs/DEPLOYMENT.md) · [DEMO SCRIPT & 3×3 declaration](docs/DEMO.md)
