"""Feature 2: regulatory change intelligence - structural diff between two versions of a regulation."""
from __future__ import annotations

from app.compliance import text as T


def _sim(a: dict, b: dict) -> float:
    ta, tb = set(T.tokens(a["text"])), set(T.tokens(b["text"]))
    return len(ta & tb) / len(ta | tb) if ta | tb else 0.0


def _facts(old: dict, new: dict) -> list[str]:
    f = []
    for key, label in (("deadlineHours", "deadline"), ("frequencyDays", "frequency (days)"),
                       ("retentionMinHours", "min retention"), ("retentionMaxHours", "max retention")):
        if old[key] != new[key]:
            fmt = T.humanize_hours if key.endswith("Hours") else (lambda v: None if v is None else f"{v:g}")
            f.append(f"{label}: {fmt(old[key]) or 'none'} -> {fmt(new[key]) or 'none'}")
    if old["modality"] != new["modality"]:
        f.append(f"modality: {old['modality']} -> {new['modality']}")
    added = sorted(set(T.tokens(new["text"])) - set(T.tokens(old["text"])))[:8]
    removed = sorted(set(T.tokens(old["text"])) - set(T.tokens(new["text"])))[:8]
    if added:
        f.append(f"new terms: {', '.join(added)}")
    if removed:
        f.append(f"dropped terms: {', '.join(removed)}")
    return f


def diff_versions(old: list[dict], new: list[dict]) -> dict:
    remaining = list(old)
    added, modified, unchanged = [], [], []
    for n in new:
        best, best_s = None, 0.0
        for o in remaining:
            s = _sim(o, n) + (0.15 if o["clause"] == n["clause"] else 0)
            if s > best_s:
                best, best_s = o, s
        if best is not None and best_s >= 0.55:
            remaining.remove(best)
            base = _sim(best, n)
            if best["text"].strip() == n["text"].strip():
                unchanged.append(n["id"])
            else:
                modified.append({"old": best, "new": n, "similarity": round(base, 2), "changes": _facts(best, n),
                                 "materiality": "high" if any(x.startswith(("deadline", "modality", "frequency", "min retention", "max retention")) for x in _facts(best, n)) else "low"})
        else:
            added.append(n)
    return {"added": added, "removed": remaining, "modified": modified, "unchangedCount": len(unchanged)}
