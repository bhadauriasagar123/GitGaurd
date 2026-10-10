"""Turn a pytest JUnit XML into docs/TEST_REPORT.md:  pytest --junitxml=junit.xml && python -m scripts.gen_test_report junit.xml"""
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone

GROUPS = {
    "test_compliance": "Problem 1 - one test per desirable feature (14)",
    "test_scenarios_p1": "Problem 1 - feature scenarios (positive / negative / edge)",
    "test_firewall": "Problem 2 - firewall corpus (52 attacks, 20 benign) + egress/vault",
    "test_scenarios_p2": "Problem 2 - attack-class and input-source scenarios",
    "test_api": "API contract, security, idempotency, correlation, tenancy, CQRS",
    "test_production": "Production scenarios (outages, concurrency, restarts, limits, observability)",
    "test_config": "Production configuration guards",
    "test_smoke_api": "Smoke",
}


def main(path: str, out: str = "docs/TEST_REPORT.md") -> None:
    root = ET.parse(path).getroot()
    rows = defaultdict(list)
    tot = {"pass": 0, "fail": 0, "skip": 0}
    for tc in root.iter("testcase"):
        mod = tc.get("classname", "").split(".")[-1]
        status = "fail" if (tc.find("failure") is not None or tc.find("error") is not None) else "skip" if tc.find("skipped") is not None else "pass"
        tot[status] += 1
        rows[mod].append((tc.get("name"), status, float(tc.get("time", 0))))
    lines = ["# Test report", "", f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} from `{path}`.", "",
             f"**{tot['pass']} passed · {tot['fail']} failed · {tot['skip']} skipped**", ""]
    for mod, items in sorted(rows.items(), key=lambda kv: list(GROUPS).index(kv[0]) if kv[0] in GROUPS else 99):
        p = sum(1 for _, s, _ in items if s == "pass")
        lines += [f"## {GROUPS.get(mod, mod)}", f"`tests/{mod}.py` - {p}/{len(items)} passed", "", "| Test | Result | s |", "|---|---|---|"]
        lines += [f"| `{n}` | {'PASS' if s == 'pass' else 'FAIL' if s == 'fail' else 'SKIP'} | {t:.2f} |" for n, s, t in items]
        lines.append("")
    open(out, "w", encoding="utf8").write("\n".join(lines))
    print(f"wrote {out}: {tot}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "junit.xml")
