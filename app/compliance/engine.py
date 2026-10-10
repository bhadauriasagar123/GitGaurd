"""The compliance analysis engine - a PURE function of (profile, regulations, controls, evidence).

Purity is what makes the what-if simulator (feature 12) and autonomous impact analysis
(feature 11) trivial and trustworthy: both are just `analyze()` on modified inputs."""
from __future__ import annotations

import copy
import json
import re
from datetime import date

from app.compliance import changes, crossreg, gaps as G, mapping
from app.compliance.controls import parse_controls
from app.compliance.effectiveness import assess_control
from app.compliance.obligations import applicability, extract_obligations

DEFAULT_PROFILE = {"entityType": "scheduled commercial bank", "jurisdictions": ["IN"], "products": ["retail", "payments"]}


def _ver_key(v: str):
    return [int(x) if x.isdigit() else x for x in re.split(r"[.\-_ ]+", str(v))]


def analyze(state: dict, today: date | None = None, overrides: list[dict] | None = None) -> dict:
    today = today or date.today()
    profile = {**DEFAULT_PROFILE, **(state.get("profile") or {})}

    by_code: dict[str, list[dict]] = {}
    for r in state.get("regulations", []):
        by_code.setdefault(r["meta"]["code"], []).append(r)
    all_versions: dict[str, list[dict]] = {}
    latest: list[dict] = []
    for code, versions in by_code.items():
        versions.sort(key=lambda r: _ver_key(r["meta"]["version"]))
        all_versions[code] = [extract_obligations(v["text"], v["meta"]) for v in versions]
        latest.append(all_versions[code][-1])
    obligations = [o for group in latest for o in group]

    for ov in overrides or []:  # what-if: regulator changes a threshold
        for o in obligations:
            if o["regCode"] == ov.get("regCode") and (not ov.get("topic") or ov["topic"] in o["topics"]):
                if ov.get("deadlineHours") is not None:
                    o["deadlineHours"] = float(ov["deadlineHours"])
                if ov.get("frequencyDays") is not None:
                    o["frequencyDays"] = float(ov["frequencyDays"])

    in_scope, out_scope = [], []
    for o in obligations:
        a = applicability(o, profile)
        o["applicability"] = a
        (in_scope if a["applicable"] else out_scope).append(o)

    controls = {c["id"]: c for c in state.get("controls", [])}
    ev_by_ctrl: dict[str, list[dict]] = {}
    for e in state.get("evidence", []):
        ev_by_ctrl.setdefault(e["controlId"], []).append(e)
    eff = {cid: assess_control(c, ev_by_ctrl.get(cid, []), today) for cid, c in controls.items()}

    maps = mapping.build_mappings(in_scope, list(controls.values()))
    total_w = sum(o["severity"] for o in in_scope) or 1.0
    assessments, all_gaps = [], []
    credit = 0.0
    for o in in_scope:
        res = G.assess_obligation(o, maps[o["id"]], controls, eff)
        credit += o["severity"] * {"compliant": 1.0, "partial": 0.5}.get(res["status"], 0.0)
        for g in res["gaps"]:
            g["risk"] = G.prioritize(g, o, today)
            g["remediation"] = G.remediation(g, o, total_w)
            g["evidence"] = [e["id"] for cid in g["controls"] for e in ev_by_ctrl.get(cid, [])][-3:]
            all_gaps.append(g)
        assessments.append({"obligationId": o["id"], "regCode": o["regCode"], "clause": o["clause"], "text": o["text"], "status": res["status"],
                            "severity": o["severity"], "topics": o["topics"], "modality": o["modality"],
                            "mappedControls": maps[o["id"]], "supportingControls": res["supportingControls"],
                            "gapIds": [g["id"] for g in res["gaps"]], "applicability": o["applicability"]})
    all_gaps.sort(key=lambda g: -g["risk"]["riskScore"])
    score = round(credit / total_w * 100, 1)
    status_counts: dict[str, int] = {}
    for a in assessments:
        status_counts[a["status"]] = status_counts.get(a["status"], 0) + 1
    band_counts: dict[str, int] = {}
    for g in all_gaps:
        band_counts[g["risk"]["band"]] = band_counts.get(g["risk"]["band"], 0) + 1

    change_reports = []
    for code, vers in all_versions.items():
        if len(vers) >= 2:
            d = changes.diff_versions(vers[-2], vers[-1])
            change_reports.append({"regCode": code, "fromVersion": vers[-2][0]["version"] if vers[-2] else None,
                                   "toVersion": vers[-1][0]["version"] if vers[-1] else None, **d})

    return {
        "asOf": today.isoformat(), "profile": profile, "complianceScore": score,
        "counts": {"regulations": len(by_code), "obligations": len(obligations), "inScope": len(in_scope), "outOfScope": len(out_scope),
                   "controls": len(controls), "evidence": sum(len(v) for v in ev_by_ctrl.values()), "gaps": len(all_gaps),
                   "byStatus": status_counts, "gapsByBand": band_counts},
        "obligations": in_scope + out_scope, "assessments": assessments, "controls": list(controls.values()),
        "controlEffectiveness": list(eff.values()), "gaps": all_gaps,
        "crossRegulation": crossreg.cross_regulation(in_scope, maps), "contradictions": crossreg.contradictions(in_scope),
        "changes": change_reports,
    }


# ---------------------------------------------------------------- what-if simulation (feature 12)
def apply_changes(state: dict, changes_: list[dict], today: date) -> tuple[dict, list[dict], list[str]]:
    s = copy.deepcopy(state)
    overrides, log = [], []
    for ch in changes_:
        t = ch.get("type")
        if t == "add_control":
            parsed = parse_controls(json.dumps([ch["control"]]))
            if not parsed:
                raise ValueError("add_control requires control.id")
            s["controls"] = [c for c in s["controls"] if c["id"] != parsed[0]["id"]] + parsed
            log.append(f"added control {parsed[0]['id']}")
            if ch.get("tested", False):
                s["evidence"].append({"id": f"SIM-{parsed[0]['id']}", "controlId": parsed[0]["id"], "date": today.isoformat(),
                                      "result": "pass", "exceptions": 0, "sampleSize": 25, "description": "simulated passing test"})
                log.append(f"  with simulated passing test evidence for {parsed[0]['id']}")
        elif t == "remove_control":
            s["controls"] = [c for c in s["controls"] if c["id"] != ch["controlId"]]
            s["evidence"] = [e for e in s["evidence"] if e["controlId"] != ch["controlId"]]
            log.append(f"removed control {ch['controlId']}")
        elif t == "update_control":
            for c in s["controls"]:
                if c["id"] == ch["controlId"]:
                    merged = {"id": c["id"], "title": c["title"], "description": c["description"], "owner": c["owner"], "type": c["type"],
                              "automation": c["automation"], "frequency": c.get("frequencyLabel") or ""}
                    merged.update({k: v for k, v in ch.items() if k in ("title", "description", "owner", "type", "automation", "frequency")})
                    c.update(parse_controls(json.dumps([merged]))[0])
                    log.append(f"updated control {c['id']}: " + ", ".join(k for k in ch if k not in ("type", "controlId")))
        elif t == "add_evidence":
            s["evidence"].append({"id": f"SIM-E{len(s['evidence'])}", "controlId": ch["controlId"], "date": ch.get("date") or today.isoformat(),
                                  "result": ch.get("result", "pass"), "exceptions": int(ch.get("exceptions", 0)), "sampleSize": 0, "description": "simulated"})
            log.append(f"added {ch.get('result', 'pass')} test evidence for {ch['controlId']}")
        elif t == "change_regulation":
            overrides.append(ch)
            log.append(f"regulator change on {ch.get('regCode')}: " + ", ".join(f"{k}={v}" for k, v in ch.items() if k in ("deadlineHours", "frequencyDays", "topic")))
        elif t == "set_profile":
            s["profile"] = {**(s.get("profile") or {}), **{k: v for k, v in ch.items() if k in ("entityType", "jurisdictions")}}
            log.append("changed bank profile")
        else:
            raise ValueError(f"unknown change type: {t}")
    return s, overrides, log


def simulate(state: dict, changes_: list[dict], today: date | None = None) -> dict:
    today = today or date.today()
    before = analyze(state, today)
    new_state, overrides, log = apply_changes(state, changes_, today)
    after = analyze(new_state, today, overrides)
    b_gaps = {g["id"]: g for g in before["gaps"]}
    a_gaps = {g["id"]: g for g in after["gaps"]}
    b_stat = {a["obligationId"]: a["status"] for a in before["assessments"]}
    shifts = [{"obligationId": a["obligationId"], "text": a["text"][:140], "from": b_stat.get(a["obligationId"], "n/a"), "to": a["status"]}
              for a in after["assessments"] if b_stat.get(a["obligationId"]) != a["status"]]
    return {
        "applied": log,
        "before": {"score": before["complianceScore"], "gaps": len(before["gaps"]), "byBand": before["counts"]["gapsByBand"]},
        "after": {"score": after["complianceScore"], "gaps": len(after["gaps"]), "byBand": after["counts"]["gapsByBand"]},
        "deltaScore": round(after["complianceScore"] - before["complianceScore"], 1),
        "gapsResolved": [{"id": g["id"], "title": g["title"], "obligation": g["obligation"][:120]} for k, g in b_gaps.items() if k not in a_gaps],
        "gapsIntroduced": [{"id": g["id"], "title": g["title"], "detail": g["detail"], "risk": g["risk"]} for k, g in a_gaps.items() if k not in b_gaps],
        "obligationStatusShifts": shifts,
        "newContradictions": len(after["contradictions"]) - len(before["contradictions"]),
    }


CREDIT = {"compliant": 1.0, "partial": 0.5}


def score_breakdown(assessments: list[dict], score: float) -> dict:
    """Explain the headline score: how many points each status contributes and which obligations cost the most.
    Points = credit x severity / sum(severity) x 100, so the contributions add up to `score` exactly."""
    total = sum(a["severity"] for a in assessments) or 1.0
    by_status: dict[str, dict] = {}
    losses = []
    for a in assessments:
        c = CREDIT.get(a["status"], 0.0)
        d = by_status.setdefault(a["status"], {"count": 0, "weight": 0.0, "points": 0.0})
        d["count"] += 1
        d["weight"] += a["severity"]
        d["points"] += c * a["severity"] / total * 100
        if c < 1.0:
            losses.append({"obligationId": a["obligationId"], "regCode": a["regCode"], "clause": a["clause"], "status": a["status"],
                           "pointsLost": round((1 - c) * a["severity"] / total * 100, 1), "text": a["text"][:140]})
    losses.sort(key=lambda x: -x["pointsLost"])
    return {"formula": "score = sum(credit x severity) / sum(severity) x 100;  credit: compliant 1.0, partial 0.5, non-compliant 0, no control 0",
            "byStatus": {k: {"count": v["count"], "weight": round(v["weight"], 2), "points": round(v["points"], 1)} for k, v in by_status.items()},
            "totalWeight": round(total, 2), "scoreCheck": round(sum(v["points"] for v in by_status.values()), 1),
            "pointsLost": round(100 - score, 1), "topLosses": losses[:3],
            "plainCompliantShare": round(100 * by_status.get("compliant", {"count": 0})["count"] / max(len(assessments), 1), 1)}
