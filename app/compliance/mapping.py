"""Feature 5: regulatory-to-control mapping (hybrid lexical-semantic + topic taxonomy), explainable."""
from __future__ import annotations

from app.compliance import text as T

MAPPED, WEAK = 0.45, 0.30
RELATED = {"breach-notification": {"incident-reporting"}, "incident-reporting": {"breach-notification"}}


def _expand(topics: list[str]) -> set[str]:
    out = set(topics)
    for t in topics:
        out |= RELATED.get(t, set())
    return out


def build_mappings(obligations: list[dict], controls: list[dict], top_k: int = 3) -> dict[str, list[dict]]:
    otoks = {o["id"]: T.tokens(o["text"]) for o in obligations}
    ctoks = {c["id"]: T.tokens(c["text"]) for c in controls}
    tf = T.TfIdf(list(otoks.values()) + list(ctoks.values()))
    ovec = {k: tf.vec(v) for k, v in otoks.items()}
    cvec = {k: tf.vec(v) for k, v in ctoks.items()}
    out: dict[str, list[dict]] = {}
    for o in obligations:
        cands = []
        for c in controls:
            sim = T.TfIdf.cosine(ovec[o["id"]], cvec[c["id"]])
            shared = sorted(_expand(o["topics"]) & _expand(c["topics"]))
            topic = min(1.0, len(shared) / len(o["topics"])) if o["topics"] else 0.0
            if not shared and sim < 0.3:
                continue
            score = round(0.5 * min(1.0, sim * 2.2) + 0.5 * topic, 3)
            if score < WEAK:
                continue
            common = sorted(set(otoks[o["id"]]) & set(ctoks[c["id"]]), key=lambda t: -tf.idf.get(t, 0))[:6]
            cands.append({"controlId": c["id"], "score": score, "strength": "strong" if score >= MAPPED and (topic >= 0.6 or sim >= 0.5) else "weak",
                          "sharedTopics": shared, "sharedTerms": common, "similarity": round(sim, 3),
                          "rationale": f"topics {shared or 'none'}; lexical overlap on {common[:4]}"})
        cands.sort(key=lambda x: -x["score"])
        out[o["id"]] = cands[:top_k]
    return out
