# Delivery agents — build, review, release and deploy through agents

Every step between "developer pushes" and "customers use it" is performed or reviewed by an agent in `scripts/ci_agents/`. They run **inside Azure DevOps Pipelines** (free; no Azure subscription needed) and work the same locally.

```
 Pull request ─┬─> Pipeline Review Agent ──┐
               ├─> PR Review Agent ────────┤   (comments on the PR; blocks on secrets / missing migration / injection-in-diff…)
               └─> Build + tests + SAST + CVE + secret scan ─> Build Review Agent ─┤
                                                                                   ▼
 develop / main ──────────────────────────────────────────────> Deploy Agent (staging) ─> smoke suite (36 checks)
                                                                                   │ pass
 main only ───> Release Gate Agent (GO / NO-GO with reasons) ─> HUMAN approval (Environment) ─> Deploy Agent (production) ─> smoke ─┐
                                                                                                                     fail ─> rollback
```

| Agent | Command | Decides | Can block? |
|---|---|---|---|
| **PR Review** | `python -m scripts.ci_agents pr-review --base origin/main [--llm] [--post]` | committed secrets (AWS/GitHub/private keys, `*_TOKEN = "…"`), ORM change without Alembic migration, app change without tests, security-sensitive paths (auth, crypto, firewall, infra, pipeline) → security reviewer, firewall/model change → accuracy gate, new dependencies, debug leftovers, risky constructs (`shell=True`, `verify=False`, `eval`), `\|\| true` masking, oversized PRs, **prompt-injection text inside the diff** | **Yes** (deterministic rules). The optional LLM review is advisory — an `llm`-sourced finding is automatically downgraded to a warning |
| **Pipeline Review** | `… pipeline-review` | the delivery definition itself: required gates present (tests, SAST, CVE, secret scan, firewall gate, smoke, agents), deployments bound to Environments, no secret echo / curl-pipe-shell / literal secrets, prod gated to `main`, staging stage exists; Bicep hardening (HTTPS-only, TLS1.2, FTPS off, `@secure()` params without defaults); Dockerfile (non-root, healthcheck, no `latest`) | Yes |
| **Build Review** | `… build-review --junit junit.xml --bandit … --audit … --coverage …` | trusts the evidence: failed tests, **deleted or uncollected tests** (baseline in `ci/baseline.json`), excessive skips, bandit medium/high, vulnerable dependencies, coverage floor | Yes |
| **Release Gate** | `… release-gate --target staging\|production …` | aggregates all reports; production additionally needs a **passing staging smoke report**; flags security-sign-off when sensitive files changed; prints GO/NO-GO and reasons | Yes — and it still leaves the final approval to a human |
| **Deploy** | `… deploy --target azure-webapp\|webhook\|noop [--execute]` | deploys through a pluggable target (Azure App Service, any host with a deploy hook such as Render/Railway/Koyeb, or noop), waits for `/readyz`, runs `scripts.prod_smoke`, **rolls back** when verification fails; **dry-run by default** | Yes (fails the stage) |

## Design rules (why it is safe to trust them)

1. **Gates are deterministic and verifiable.** A model may *advise*; it can never veto or approve. (`Finding` forces `source="llm"` to at most `warn`.)
2. **The diff is untrusted input.** Added lines are scanned by the project's own Prompt Injection Firewall before any model reads them; if it looks like instructions to an AI reviewer, the LLM step is skipped and a human is told to read the diff. Known attack-string directories (`app/firewall`, `app/benchmark`, `tests`, `docs`, `scripts`) are exempt from that scan because they legitimately contain such text.
3. **Humans keep production.** The `regguard-prod` Environment needs an Approval check. The Release Gate decides whether it is even worth asking.
4. **Agents are reviewed too.** `scripts/ci_agents/` is on the security-sensitive path list, and the Pipeline Review Agent reviews the pipeline that runs the agents.
5. **No silent weakening.** Removing a test, a scan or a stage fails a build (`tests-removed`, `missing-gate`).
6. **Everything leaves evidence.** Each agent writes JSON (`--out`) and markdown (PR comment / log); reports are published as pipeline artifacts.

## Set-up (≈15 minutes, all free)

1. **Azure DevOps** → new Project → push the repo. **Pipelines → New → existing YAML → `azure-pipelines.yml`.**
2. **Library → variable group `regguard-secrets`** (mark secrets):
   `STAGING_URL`, `PROD_URL`, `STAGING_API_KEYS`, `PROD_API_KEYS`, plus for `webhook`: `STAGING_DEPLOY_HOOK_URL`, `PROD_DEPLOY_HOOK_URL` (and optional `*_ROLLBACK_HOOK_URL`); for `azure-webapp`: `AZURE_SERVICE_CONNECTION`, `RESOURCE_GROUP`, `LOCATION`, `STAGING_WEBAPP_NAME`, `PROD_WEBAPP_NAME`, `STAGING_PG_PASSWORD`, `STAGING_REDIS_URL`, `STAGING_ENC_KEY`; optional `FOUNDRY_ENDPOINT`, `FOUNDRY_KEY` (enables the advisory LLM reviewer).
3. **Pipelines → Environments:** create `regguard-staging` and `regguard-prod`; on `regguard-prod` add **Approvals** (and optionally a *Business hours* check).
4. **Repos → Branches → Branch policies** for `main` and `develop`: **Build validation** = this pipeline (required), **minimum reviewers**, **comment resolution**, and add the repo's `CODEOWNERS`-style reviewers for the security-sensitive paths.
5. **Grant the build identity "Contribute to pull requests"** (Repos → Security) so the PR Review Agent can post its comment with `System.AccessToken`.
6. Free-tier parallelism: request the free grant for private projects, or register a **self-hosted agent** (your machine) and replace `vmImage: ubuntu-latest` by `name: <pool>`.

Branch model: `feature/*` → PR → `develop` (auto-deploys to **staging**) → PR → `main` (Release Gate → approval → **production**). Staging and production must use **separate** databases, Redis instances and API keys.

## Run the agents locally

```bash
python -m scripts.ci_agents pipeline-review
python -m scripts.ci_agents pr-review --base main            # reviews your branch vs main
python -m scripts.ci_agents build-review --junit junit.xml
python -m scripts.ci_agents deploy --target webhook          # dry-run: prints the plan
```

## Using the same reviewers inside Claude Code

`.claude/agents/` defines `pr-reviewer`, `security-reviewer` and `release-manager` sub-agents that wrap the same CLI and add judgement on top (they read the code, run the agents, and explain findings). They are advisory helpers for people; the pipeline gates remain the deterministic agents above.

## Limits (honest)

* Verified here: unit tests for every agent and failure path, a real end-to-end PR review on a git branch (it found a bug in the agent itself — fixed), and the pipeline passing its own review. **Not verified:** execution inside a real Azure DevOps organisation, the PR-comment REST call, `az webapp deploy`, or a real host's deploy hook.
* Deterministic review catches classes of mistake it was written for; it is not a substitute for a human reading security-sensitive changes.
* Deployment slots/rollback via `az` need a Standard App Service plan; on F1/B1 rollback means redeploying the previous artifact.
