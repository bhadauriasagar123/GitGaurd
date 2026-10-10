"""Build Review Agent: reads the build's evidence (JUnit, bandit, pip-audit, coverage) and decides whether the build is
trustworthy - including guarding against *silent weakening* (deleted tests, skipped tests, falling coverage)."""
from __future__ import annotations

import json
import os
from defusedxml import ElementTree as ET

from scripts.ci_agents.common import Report

DEFAULT_BASELINE = {"min_tests": 330, "max_skipped": 3, "min_coverage": 0.70}


def load_baseline(path: str = "ci/baseline.json") -> dict:
    if os.path.exists(path):
        with open(path, encoding="utf8") as fh:
            return {**DEFAULT_BASELINE, **json.load(fh)}
    return dict(DEFAULT_BASELINE)


def review(junit: str | None, bandit_json: str | None = None, audit_json: str | None = None, coverage_xml: str | None = None,
           baseline: dict | None = None) -> Report:
    b = baseline or load_baseline()
    r = Report("Build Review Agent")
    if not junit or not os.path.exists(junit):
        r.add("block", "no-test-evidence", "No JUnit results found: a build without test evidence cannot be released.")
        return r
    root = ET.parse(junit).getroot()
    cases = list(root.iter("testcase"))
    failed = [c for c in cases if c.find("failure") is not None or c.find("error") is not None]
    skipped = [c for c in cases if c.find("skipped") is not None]
    r.facts.update(tests=len(cases), failed=len(failed), skipped=len(skipped))
    for c in failed[:10]:
        r.add("block", "test-failed", f"{c.get('classname')}::{c.get('name')}")
    if len(cases) < b["min_tests"]:
        r.add("block", "tests-removed", f"{len(cases)} tests ran but the baseline is {b['min_tests']}: tests were deleted or not collected. Update ci/baseline.json only with reviewer approval.")
    if len(skipped) > b["max_skipped"]:
        r.add("warn", "too-many-skipped", f"{len(skipped)} skipped tests (baseline allows {b['max_skipped']}).")

    if bandit_json and os.path.exists(bandit_json):
        issues = json.load(open(bandit_json, encoding="utf8")).get("results", [])
        bad = [i for i in issues if i.get("issue_severity") in ("MEDIUM", "HIGH")]
        r.facts["bandit_medium_high"] = len(bad)
        for i in bad[:10]:
            r.add("block", f"sast-{i.get('test_id')}", f"{i.get('issue_text')}", f"{i.get('filename')}:{i.get('line_number')}")
    else:
        r.add("warn", "no-sast-evidence", "No bandit report supplied.")

    if audit_json and os.path.exists(audit_json):
        data = json.load(open(audit_json, encoding="utf8"))
        deps = data.get("dependencies", data if isinstance(data, list) else [])
        vulns = [(d.get("name"), v.get("id")) for d in deps for v in d.get("vulns", [])]
        r.facts["vulnerable_dependencies"] = len(vulns)
        for name, vid in vulns[:10]:
            r.add("block", "dependency-cve", f"{name}: {vid}")
    else:
        r.add("warn", "no-sca-evidence", "No pip-audit report supplied.")

    if coverage_xml and os.path.exists(coverage_xml):
        rate = float(ET.parse(coverage_xml).getroot().get("line-rate", 0))
        r.facts["coverage"] = round(rate, 3)
        if rate < b["min_coverage"]:
            r.add("block", "coverage-dropped", f"Line coverage {rate:.0%} is below the {b['min_coverage']:.0%} floor.")
    return r
