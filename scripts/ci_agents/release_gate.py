"""Release Gate Agent: aggregates every other agent's evidence into a GO / NO-GO decision with reasons.
It never deploys by itself and never replaces the human approval on the production Environment - it makes that
approval informed (and refuses to even ask when the evidence is bad)."""
from __future__ import annotations

import json
import os

from scripts.ci_agents.common import Report


def _load(path: str | None) -> dict | None:
    if path and os.path.exists(path):
        with open(path, encoding="utf8") as fh:
            return json.load(fh)
    return None


def decide(target: str, pr: str | None, build: str | None, pipeline: str | None, smoke_staging: str | None = None) -> Report:
    r = Report("Release Gate Agent")
    r.facts["target"] = target
    evidence = {"build": _load(build), "pipeline": _load(pipeline), "pr": _load(pr)}
    for name in ("build", "pipeline"):
        ev = evidence[name]
        if ev is None:
            r.add("block", f"no-{name}-evidence", f"Missing {name} review report: refusing to release without it.")
        elif ev["verdict"] == "block":
            r.add("block", f"{name}-blocked", f"{ev['agent']} blocked: " + "; ".join(f['rule'] for f in ev["findings"] if f["level"] == "block")[:300])
        elif ev["verdict"] == "review":
            r.add("warn", f"{name}-warnings", f"{ev['agent']} raised warnings ({sum(1 for f in ev['findings'] if f['level'] == 'warn')}).")
    if evidence["pr"] and evidence["pr"]["verdict"] == "block":
        r.add("block", "pr-blocked", "PR Review Agent blocked this change set.")
    if evidence["pr"] and any(f["rule"] == "security-sensitive-path" for f in evidence["pr"]["findings"]):
        r.add("warn", "needs-security-signoff", "Change touches security-sensitive files: the production approval must include a security reviewer.")
    if target == "production":
        s = _load(smoke_staging)
        if s is None:
            r.add("block", "no-staging-smoke", "Production requires a passing staging smoke-test report (scripts.prod_smoke on staging).")
        elif not s.get("passed"):
            r.add("block", "staging-smoke-failed", f"Staging smoke test failed: {s.get('failed')} check(s).")
        else:
            r.facts["staging_checks"] = s.get("total")
    r.facts["decision"] = "NO-GO" if r.verdict == "block" else "GO (human approval still required for production)" if target == "production" else "GO"
    return r
