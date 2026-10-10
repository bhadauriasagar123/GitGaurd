"""Shared types for the delivery agents: Finding / Report, markdown rendering, PR-comment posting."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

LEVELS = {"block": 3, "warn": 2, "info": 1}


@dataclass
class Finding:
    level: str  # block | warn | info
    rule: str
    message: str
    file: str = ""
    source: str = "deterministic"  # deterministic | llm  (LLM findings can never block)

    def __post_init__(self):
        if self.source == "llm" and self.level == "block":
            self.level = "warn"  # an LLM may advise, it may not veto: only verifiable checks gate delivery


@dataclass
class Report:
    agent: str
    findings: list[Finding] = field(default_factory=list)
    facts: dict = field(default_factory=dict)

    def add(self, level: str, rule: str, message: str, file: str = "", source: str = "deterministic") -> None:
        self.findings.append(Finding(level, rule, message, file, source))

    @property
    def verdict(self) -> str:
        top = max((LEVELS[f.level] for f in self.findings), default=0)
        return "block" if top == 3 else "review" if top == 2 else "pass"

    def to_dict(self) -> dict:
        return {"agent": self.agent, "verdict": self.verdict, "facts": self.facts, "findings": [asdict(f) for f in self.findings]}

    def markdown(self) -> str:
        icon = {"block": "⛔", "review": "⚠️", "pass": "✅"}[self.verdict]
        out = [f"### {icon} {self.agent}: **{self.verdict.upper()}**", ""]
        if self.facts:
            out.append("  ".join(f"`{k}`={v}" for k, v in self.facts.items()))
            out.append("")
        for lvl in ("block", "warn", "info"):
            items = [f for f in self.findings if f.level == lvl]
            if items:
                out.append(f"**{lvl.upper()}**")
                out += [f"- `{f.rule}`{' (' + f.file + ')' if f.file else ''}{' [LLM advisory]' if f.source == 'llm' else ''}: {f.message}" for f in items]
                out.append("")
        if not self.findings:
            out.append("No findings.")
        return "\n".join(out)


def write_report(report: Report, path: str | None) -> None:
    if path:
        with open(path, "w", encoding="utf8") as fh:
            json.dump(report.to_dict(), fh, indent=2)


def post_pr_comment(markdown: str) -> str:
    """Post to the current Azure DevOps pull request (needs SYSTEM_ACCESSTOKEN + build variables). Returns a status string.
    Outside a PR build it just prints, so the agent is usable locally."""
    import httpx

    token = os.environ.get("SYSTEM_ACCESSTOKEN")
    pr = os.environ.get("SYSTEM_PULLREQUEST_PULLREQUESTID")
    uri, project, repo = os.environ.get("SYSTEM_COLLECTIONURI"), os.environ.get("SYSTEM_TEAMPROJECT"), os.environ.get("BUILD_REPOSITORY_ID")
    if not all([token, pr, uri, project, repo]):
        return "not in a PR build - comment not posted"
    url = f"{uri.rstrip('/')}/{project}/_apis/git/repositories/{repo}/pullRequests/{pr}/threads?api-version=7.1"
    body = {"comments": [{"parentCommentId": 0, "content": markdown[:30000], "commentType": 1}], "status": 1}
    r = httpx.post(url, json=body, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    return f"posted ({r.status_code})" if r.status_code < 300 else f"post failed ({r.status_code})"
