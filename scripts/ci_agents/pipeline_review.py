"""Pipeline Review Agent: static review of the delivery definition itself (azure-pipelines.yml + Bicep + Dockerfile).
A weakened pipeline silently weakens every later release, so the pipeline is reviewed like code."""
from __future__ import annotations

import re

import yaml

from scripts.ci_agents.common import Report

REQUIRED_STEPS = {"pytest": "automated tests", "bandit": "SAST", "pip-audit": "dependency CVE scan", "detect-secrets": "secret scan",
                  "eval_firewall": "firewall quality gate", "prod_smoke": "post-deploy smoke test", "ci_agents": "delivery agents"}


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def review(pipeline_path: str = "azure-pipelines.yml", bicep_path: str = "infra/main.bicep", dockerfile: str = "Dockerfile") -> Report:
    r = Report("Pipeline Review Agent")
    text = open(pipeline_path, encoding="utf8").read()
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as e:
        r.add("block", "invalid-yaml", f"Pipeline YAML does not parse: {e}")
        return r
    # What Azure DevOps validates with the DEFAULT parameters. Service connections are checked at PARSE time, so a runtime
    # `condition:` does not make an Azure-only step safe on the free path: it must be inside a compile-time `${{ if }}` block.
    from scripts.ci_agents import yamlexpand
    compiled = yamlexpand.expand(doc, yamlexpand.defaults(doc))
    for sub in yamlexpand.find_values(compiled, "azureSubscription"):
        r.add("block", "azure-connection-on-default-path",
              f"Default parameters still reference an Azure service connection ({str(sub)[:40] or 'empty'}). Parsing fails without one. Wrap Azure-only steps in `${{{{ if eq(parameters.deployTarget, 'azure-webapp') }}}}:` and default to the free target.")
    for sub in yamlexpand.find_values(doc, "azureSubscription"):
        if "$(" in str(sub):
            r.add("block", "azure-connection-variable", "azureSubscription must not be a $(variable): it is resolved too late for parse-time validation. Use a compile-time parameter.")
    steps = [s for n in _walk(doc) for s in (n.get("steps") or []) if isinstance(s, dict)]
    scripts = "\n".join(str(s.get("script") or s.get("bash") or s.get("inlineScript") or (s.get("inputs") or {}).get("inlineScript") or "") for s in steps)
    r.facts.update(stages=len(doc.get("stages", [])), steps=len(steps))

    for needle, what in REQUIRED_STEPS.items():
        if needle not in text:
            r.add("block", "missing-gate", f"Pipeline has no {what} step ('{needle}').")
    stages = [s.get("stage") for s in doc.get("stages", [])]
    if not any(re.search("stag", str(s), re.I) for s in stages):
        r.add("warn", "no-staging-stage", "No staging stage: production would be the first place a change is exercised.")
    deployments = [n for n in _walk(doc) if "deployment" in n]
    for d in deployments:
        if not d.get("environment"):
            r.add("block", "deployment-without-environment", f"Deployment '{d['deployment']}' has no `environment` (no approvals/audit trail possible).")
    if not re.search(r"environment:\s*\S*prod", text, re.I):
        r.add("warn", "no-prod-environment", "No production Environment found: add one with an Approval check.")
    if "|| true" in scripts:
        r.add("warn", "masked-failure", "`|| true` masks failures in a script step (allowed only for best-effort cleanup).")
    if re.search(r"echo\s+.*\$\((?:[A-Z_]*(?:KEY|SECRET|PASSWORD|TOKEN))", scripts):
        r.add("block", "secret-echo", "A script echoes a secret variable into the build log.")
    if re.search(r"curl[^\n|]*\|\s*(?:sudo\s+)?(?:ba)?sh", scripts):
        r.add("block", "curl-pipe-shell", "Pipeline pipes a download into a shell.")
    if "condition:" not in text or "refs/heads/main" not in text:
        r.add("warn", "deploy-not-branch-gated", "Deployment is not restricted to the main branch via `condition`.")
    if not re.search(r"variables:\s*\n\s*-\s*group:", text):
        r.add("warn", "no-variable-group", "No Library variable group: secrets must not live in YAML.")
    if re.search(r"(?i)(password|secret|apikey|api_key)\s*:\s*['\"]?[A-Za-z0-9+/=]{16,}", text):
        r.add("block", "literal-secret", "A literal secret appears in the pipeline YAML.")

    try:
        bicep = open(bicep_path, encoding="utf8").read()
        for needle, msg in (("httpsOnly: true", "HTTPS-only is not enforced"), ("minTlsVersion: '1.2'", "TLS 1.2 minimum missing"), ("ftpsState: 'Disabled'", "FTPS is not disabled")):
            if needle not in bicep:
                r.add("block", "bicep-hardening", msg, bicep_path)
        decorators: list[str] = []
        for ln in bicep.splitlines():
            s = ln.strip()
            if s.startswith("@"):
                decorators.append(s)
                continue
            m = re.match(r"param\s+(\w+)\s+string(?:\s*=\s*(.*))?$", s)
            if m and re.search(r"password|key|secret|redisurl|apikeys", m.group(1), re.I) and "Name" not in m.group(1):
                default = (m.group(2) or "").strip()
                if "@secure()" not in decorators:
                    r.add("block", "bicep-secret-param", f"Secret parameter '{m.group(1)}' is not @secure().", bicep_path)
                elif default not in ("", "''"):
                    r.add("block", "bicep-secret-default", f"Secret parameter '{m.group(1)}' has a non-empty default.", bicep_path)
            decorators = []
    except FileNotFoundError:
        r.add("warn", "no-bicep", "infra/main.bicep not found.")
    try:
        df = open(dockerfile, encoding="utf8").read()
        if "USER " not in df:
            r.add("block", "docker-root", "Container runs as root.", dockerfile)
        if "HEALTHCHECK" not in df:
            r.add("warn", "docker-no-healthcheck", "No HEALTHCHECK.", dockerfile)
        if re.search(r"FROM\s+\S+:latest", df):
            r.add("warn", "docker-latest-tag", "Unpinned `latest` base image.", dockerfile)
    except FileNotFoundError:
        r.add("warn", "no-dockerfile", "Dockerfile not found.")
    return r
