"""Feature 6: control effectiveness assessment = design effectiveness x operating effectiveness."""
from __future__ import annotations

from datetime import date

TYPE_SCORE = {"preventive": 90, "detective": 75, "corrective": 60, "directive": 55}
AUTO_SCORE = {"automated": 100, "semi-automated": 70, "semiautomated": 70, "manual": 45}


def _freq_score(days: float | None) -> float:
    if days is None:
        return 40
    for limit, sc in ((1.5, 100), (8, 85), (32, 70), (93, 55), (185, 40)):
        if days <= limit:
            return sc
    return 30


def assess_control(control: dict, evidence: list[dict], today: date) -> dict:
    design = (TYPE_SCORE.get(control["type"], 60) * 0.45 + AUTO_SCORE.get(control["automation"], 45) * 0.35
              + _freq_score(control.get("frequencyDays")) * 0.20)
    if not control.get("owner"):
        design -= 10
    ev = sorted(evidence, key=lambda e: e["date"])
    if not ev:
        return {"controlId": control["id"], "designScore": round(design), "operatingScore": None, "overall": round(min(design * 0.4, 49)),
                "rating": "untested", "evidenceCount": 0, "lastTested": None, "ageDays": None, "passRate": None,
                "freshness": None, "notes": ["No test evidence on file - effectiveness cannot be demonstrated"]}
    last = date.fromisoformat(ev[-1]["date"])
    age = (today - last).days
    freq = control.get("frequencyDays") or 92
    horizon = max(freq, 92)  # testing cadence: at least quarterly even for continuous/daily controls
    freshness = 100 if age <= horizon * 1.1 + 3 else 60 if age <= horizon * 2.2 + 7 else 20
    pr = sum({"pass": 1, "partial": 0.5, "fail": 0}[e["result"]] for e in ev) / len(ev)
    exc_pen = min(30, 5 * sum(e["exceptions"] for e in ev[-3:]))
    latest_fail = ev[-1]["result"] == "fail"
    operating = max(0.0, 0.5 * freshness + 0.5 * pr * 100 - exc_pen - (25 if latest_fail else 0))
    overall = round(0.4 * design + 0.6 * operating)
    notes = []
    if freshness < 100:
        notes.append(f"Last test {age} days ago exceeds the {horizon:g}-day cadence")
    if latest_fail:
        notes.append("Most recent test FAILED")
    if exc_pen:
        notes.append(f"{sum(e['exceptions'] for e in ev[-3:])} exception(s) in recent tests")
    rating = "effective" if overall >= 75 else "partially_effective" if overall >= 50 else "ineffective"
    return {"controlId": control["id"], "designScore": round(design), "operatingScore": round(operating), "overall": overall,
            "rating": rating, "evidenceCount": len(ev), "lastTested": ev[-1]["date"], "ageDays": age, "passRate": round(pr, 2),
            "freshness": freshness, "notes": notes}
