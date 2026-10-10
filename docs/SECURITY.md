# Security hardening & VAPT checklist

Mapped to OWASP Top 10 (2021), OWASP API Security Top 10 (2023) and OWASP LLM Top 10. "Test" = automated test that proves it.

| Risk | Control | Test |
|---|---|---|
| A01 Broken access control / API1 BOLA | Per-request tenant derived from the API key (never from input); repository filters by tenant; other tenant gets 404 | `test_tenant_isolation` |
| API5 Function-level authZ | RBAC viewer < analyst < admin on every route | `test_auth_and_rbac` |
| A02 Cryptographic failures | AES-256-GCM at rest with tenant:doc AAD; API keys stored as SHA-256, compared in constant time over the whole ring; HSTS | `test_cross_tenant_ciphertext…`, `test_document_content_never_leaks…` |
| A03 Injection (SQL) | SQLAlchemy parameterised queries only; no string-built SQL | code review + bandit |
| A03 Injection (prompt) / LLM01 | Prompt Injection Firewall on all inputs; spotlighting; least-privilege (LLM sees structured findings only, has no tools) | `test_firewall.py` (52 attacks, 20 benign) |
| LLM02 Insecure output handling | Egress guard on outputs; UI renders with `textContent` only | `test_egress_*`, `test_egress_guard_withholds…` |
| LLM06 Sensitive info disclosure | Prompt Vault canary + n-gram guard, secret/exfil-URL redaction, no raw-document API, audited admin reveal | `test_assistant_blocks_prompt_extraction…` |
| LLM04 / API4 Resource consumption | Body limit (chunk-aware), per-field length limits, Redis rate limits (heavy endpoints stricter), bounded regexes, decode depth/variant caps, zip-bomb guard, PDF page cap | `test_body_size_limit`, `test_redos_resistance`, `test_docx_zip_bomb_rejected`, `test_rate_limit` |
| A04 Insecure design | Fail-closed Redis dependency, idempotency, locks, quarantine instead of silent drop | `test_idempotent_*`, `test_poisoned_document…` |
| A05 Misconfiguration | Production refuses to start with default keys / SQLite / fakeredis; docs disabled in prod; CSP `default-src 'self'`, `frame-ancestors 'none'`, nosniff, no-store, COOP/CORP, Permissions-Policy; server header stripped; CORS allow-list only | `test_config.py`, `test_security_headers` |
| A06 Vulnerable components | `pip-audit` + `bandit` + secret scan gates in the pipeline | `azure-pipelines.yml` |
| A07 Auth failures | Missing/invalid key → 401 + `WWW-Authenticate`; keys ≥24 chars enforced in prod; per-actor rate limits | `test_auth_and_rbac` |
| A08 Integrity failures | Hash-chained audit log (HMAC), verify endpoint detects edits | `test_reveal_is_audited…tamper` |
| A09 Logging failures | Structured JSON logs with correlation id, tenant, actor; redaction of keys/content; every block/reveal/egress intervention audited | `test_correlation_*` |
| A10 SSRF | The service never fetches user-supplied URLs (web/HTML content is supplied as text) | by design |
| Log/header injection | Incoming correlation ids are validated (`[A-Za-z0-9._-]{8,64}`) or replaced | `test_correlation_id_generated_echoed_and_sanitised` |
| Info leakage in errors | RFC 7807 with correlation id; unhandled errors return a generic message | `test_unhandled_exception_masks_internals` |
| Mass assignment | Pydantic models `extra="forbid"` | `test_404_and_validation_errors_are_structured` |
| Replay / double submit | `Idempotency-Key` protocol | `test_idempotent_*` |

## Operational hardening to apply in Azure

* Keep secrets in **Key Vault** (App Service Key Vault references) instead of App Settings once you leave the hackathon tier; rotate `API_KEYS`/`ENC_KEY` (ENC_KEY rotation requires re-encrypting documents – add a key-id column when you need it).
* PostgreSQL: enforce TLS (`?ssl=require`), restrict the firewall to the App Service outbound IPs or use VNet integration + private endpoint, enable automated backups (already 7 days in Bicep).
* Redis: TLS (`rediss://`), password auth, network-restricted.
* Put **Azure Front Door/WAF** (or App Gateway WAF) in front for OWASP CRS, DDoS and IP rate limiting; the in-app limiter is a second line.
* Defender for Cloud (free CSPM tier), Azure Policy "HTTPS only", diagnostic logs → Log Analytics (workspace-based Application Insights; the JSON logs already carry correlation ids).
* Pen-test checklist for the VAPT run: auth bypass, IDOR across tenants, oversized/malformed JSON, Unicode/encoding evasion of the firewall, ReDoS (corpus in `tests/`), zip-bomb DOCX, prompt-extraction through the copilot, header injection, rate-limit bypass via header spoofing (we key on API key, not client IP), idempotency-key reuse across tenants (keys are tenant-scoped).

## Known gaps (be upfront with judges)

* Redis protocol behaviour is verified with `fakeredis` in tests and not against a live Redis in this repository's CI; run the smoke test after provisioning.
* No SSO/OIDC — API keys only. For production put Entra ID in front (App Service Easy Auth) and map groups to roles.
* Firewall is heuristic. Add a model-based classifier (e.g. Azure AI Content Safety *Prompt Shields*) as an additional signal; the engine's scoring layer accepts extra findings without change.
