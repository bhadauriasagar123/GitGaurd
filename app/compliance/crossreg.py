"""Features 13 & 14: cross-regulation intelligence and regulatory contradiction detection."""
from __future__ import annotations

from app.compliance import text as T
from app.compliance.mapping import _expand


def _vectors(obls):
    toks = {o["id"]: T.tokens(o["text"]) for o in obls}
    tf = T.TfIdf(list(toks.values()))
    return {k: tf.vec(v) for k, v in toks.items()}


def _pairs(obls, min_sim: float):
    vec = _vectors(obls)
    for i, a in enumerate(obls):
        for b in obls[i + 1:]:
            if a["regCode"] == b["regCode"]:
                continue
            shared = sorted(_expand(a["topics"]) & _expand(b["topics"]))
            sim = T.TfIdf.cosine(vec[a["id"]], vec[b["id"]])
            if not shared and sim < 0.4:  # no taxonomy topic in common: only very similar wording qualifies
                continue
            if sim >= min_sim:
                yield a, b, shared, sim


def cross_regulation(obls: list[dict], mappings: dict[str, list[dict]]) -> list[dict]:
    parent = {o["id"]: o["id"] for o in obls}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    link_topics: dict[str, set] = {}
    for a, b, shared, sim in _pairs(obls, 0.10):
        if sim < 0.22 and not (a["deadlineHours"] and b["deadlineHours"]):
            continue
        parent[find(a["id"])] = find(b["id"])
        link_topics.setdefault(find(a["id"]), set()).update(shared)
    groups: dict[str, list[dict]] = {}
    for o in obls:
        groups.setdefault(find(o["id"]), []).append(o)
    out = []
    for root, members in groups.items():
        regs = sorted({m["regCode"] for m in members})
        if len(regs) < 2:
            continue
        topics = sorted({t for m in members for t in m["topics"]})
        deadlines = [m["deadlineHours"] for m in members if m["deadlineHours"]]
        ctrl_count: dict[str, int] = {}
        for m in members:
            for mp in mappings.get(m["id"], []):
                if mp["strength"] == "strong":
                    ctrl_count[mp["controlId"]] = ctrl_count.get(mp["controlId"], 0) + 1
        reusable = sorted(ctrl_count, key=lambda c: -ctrl_count[c])[:3]
        out.append({
            "cluster": f"XR-{len(out) + 1}", "topics": topics[:4], "regulations": regs,
            "obligations": [{"id": m["id"], "regCode": m["regCode"], "clause": m["clause"], "text": m["text"],
                             "deadline": T.humanize_hours(m["deadlineHours"])} for m in members],
            "strictestDeadline": T.humanize_hours(min(deadlines)) if deadlines else None,
            "harmonisation": (f"Design ONE control to the strictest requirement"
                              f"{' (' + T.humanize_hours(min(deadlines)) + ')' if deadlines else ''} and map it to all {len(members)} obligations across {', '.join(regs)}."),
            "reusableControls": reusable,
        })
    return out


def contradictions(obls: list[dict]) -> list[dict]:
    found = []
    for a, b, shared, sim in _pairs(obls, 0.12):
        base = {"between": [{"id": a["id"], "regCode": a["regCode"], "clause": a["clause"], "text": a["text"]},
                            {"id": b["id"], "regCode": b["regCode"], "clause": b["clause"], "text": b["text"]}], "topics": shared}
        # 1. hard numeric conflict: minimum retention of one > maximum retention of other
        for x, y in ((a, b), (b, a)):
            if x["retentionMinHours"] and y["retentionMaxHours"] and x["retentionMinHours"] > y["retentionMaxHours"]:
                found.append({**base, "type": "HARD_CONFLICT", "severity": "critical",
                              "explanation": f"{x['regCode']} {x['clause']} requires retention >= {T.humanize_hours(x['retentionMinHours'])} but {y['regCode']} {y['clause']} caps it at {T.humanize_hours(y['retentionMaxHours'])}. Both cannot be satisfied for the same data.",
                              "resolution": "Segregate data classes / purposes, apply the legal-hold exception, or seek regulator clarification; document the rationale."})
                break
        else:
            # 2. modality conflict
            if {a["modality"], b["modality"]} == {"mandatory", "prohibited"} and sim >= 0.30 and not (
                    a["retentionMaxHours"] or b["retentionMaxHours"] or a["retentionMinHours"] or b["retentionMinHours"]):
                found.append({**base, "type": "MODALITY_CONFLICT", "severity": "high",
                              "explanation": "One regulation mandates what the other prohibits for closely matching subject matter.",
                              "resolution": "Establish jurisdictional scoping rules; escalate to Legal for precedence analysis."})
            # 3. deadline divergence
            elif a["deadlineHours"] and b["deadlineHours"] and a["deadlineHours"] != b["deadlineHours"] and sim >= 0.20:
                strict = a if a["deadlineHours"] < b["deadlineHours"] else b
                found.append({**base, "type": "DEADLINE_DIVERGENCE", "severity": "medium",
                              "explanation": f"Different deadlines for the same event: {T.humanize_hours(a['deadlineHours'])} ({a['regCode']}) vs {T.humanize_hours(b['deadlineHours'])} ({b['regCode']}).",
                              "resolution": f"Adopt the strictest ({T.humanize_hours(strict['deadlineHours'])}, {strict['regCode']}) as the internal standard so a single process satisfies both."})
    return found
