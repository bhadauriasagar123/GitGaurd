# API reference

Generated from the OpenAPI schema (`RegGuard Shield v1.0.0`). Interactive docs: `/docs` (dev/staging).

**Auth:** header `X-API-Key: <key>` (roles: `viewer` < `analyst` < `admin`; each key is bound to one tenant). **Writes:** send `Idempotency-Key: <uuid>` (replays return the original response). **Tracing:** every response carries `X-Correlation-Id`. **Errors:** RFC 7807 `application/problem+json`.


## Administration

| Method | Path | Summary | Query |
|---|---|---|---|
| POST | `/api/v1/admin/reset` | Delete all tenant data |  |
| GET | `/api/v1/audit` | Tamper-evident audit trail | limit |
| GET | `/api/v1/audit/verify` | Verify audit hash chain integrity |  |
| GET | `/api/v1/profile` | Bank profile used for applicability |  |
| PUT | `/api/v1/profile` | Put Profile |  |
| POST | `/api/v1/sample/load` | Load a dataset through the full firewalled pipeline (idempotent). dataset=real: public-regulation pack; demo: fictional test fixture | dataset |
| GET | `/api/v1/system/info` | Runtime topology (no secrets) |  |
| GET | `/api/v1/whoami` | Whoami |  |

## Compliance Intelligence

| Method | Path | Summary | Query |
|---|---|---|---|
| GET | `/api/v1/analysis/summary` | Score, counts, headline findings (features 7, 8, 9) |  |
| GET | `/api/v1/assessments` | Regulation -> control mapping and evidence-based status (features 5, 7) | status |
| POST | `/api/v1/assistant/ask` | Firewall-guarded compliance copilot (input AND output screened) |  |
| GET | `/api/v1/changes` | Regulatory change intelligence - version diffs (feature 2) |  |
| GET | `/api/v1/contradictions` | Conflicting regulatory requirements (feature 14) |  |
| GET | `/api/v1/controls` | Control framework with effectiveness (features 4, 6) |  |
| GET | `/api/v1/cross-regulation` | Overlapping obligations across regulations (feature 13) |  |
| GET | `/api/v1/gaps` | Risk-prioritised gaps with remediation (features 8, 9, 10) | minBand |
| GET | `/api/v1/impact` | Autonomous regulatory impact reports (feature 11) |  |
| GET | `/api/v1/monitoring/trend` | Ongoing monitoring - compliance score history |  |
| GET | `/api/v1/obligations` | Extracted obligations incl. applicability (features 1, 3) | regCode |
| GET | `/api/v1/trace/{obligation_id}` | End-to-end traceability chain regulation -> ... -> monitoring |  |
| POST | `/api/v1/whatif` | What-if / simulation (feature 12) - never mutates data |  |

## Ingestion

| Method | Path | Summary | Query |
|---|---|---|---|
| GET | `/api/v1/documents` | List Docs | kind |
| POST | `/api/v1/documents` | Ingest a regulation / control framework / evidence (firewalled, idempotent) |  |
| DELETE | `/api/v1/documents/{doc_id}` | Delete Doc |  |
| GET | `/api/v1/documents/{doc_id}` | Metadata only; reveal=true is admin-only and audited | reveal |

## Platform

| Method | Path | Summary | Query |
|---|---|---|---|
| GET | `/healthz` | Liveness |  |
| GET | `/readyz` | Readiness - verifies PostgreSQL and Redis |  |

## Prompt Injection Firewall

| Method | Path | Summary | Query |
|---|---|---|---|
| GET | `/api/v1/firewall/catalog` | Attack classes, rule inventory and vault status |  |
| POST | `/api/v1/firewall/egress` | Inspect model OUTPUT for prompt/document/secret leakage |  |
| GET | `/api/v1/firewall/samples` | Ready-made attack payloads for the demo |  |
| POST | `/api/v1/firewall/scan` | Scan any content before it reaches an AI agent |  |
