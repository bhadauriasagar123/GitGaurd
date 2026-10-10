"""Features 1-3: regulatory ingestion, structuring and obligation extraction."""
from __future__ import annotations

import re
from datetime import date

from app.compliance import text as T

_CLAUSE = re.compile(r"^\s*(?:(?:section|article|clause|para(?:graph)?|regulation|rule)\s+)?(\d+(?:\.\d+){0,3}[a-z]?|[A-Z]\d+(?:\.\d+)*)[.):]?\s+(\S.*)$", re.I)
_PROHIB = re.compile(r"\bin\s+no\s+(?:case|event)\b|\bunder\s+no\s+circumstances\b|\b(?:shall|must)\s+refrain\s+from\b|\b(?:shall|must|may)\s+never\b|\b(?:is|are)\s+(?:strictly\s+)?(?:barred|banned|disallowed|not\s+allowed)\b|\bno\s+(?:\w+\s+){1,3}(?:is|are|shall|may)\s+(?:permitted|allowed)\b|\b(?:shall|must)\s+not\b|\bmay\s+not\b(?!\s+exceed)|\b(?:is|are)\s+(?:strictly\s+)?prohibited\b|\bshall\s+never\b|\bnot\s+permitted\b|\bforbidden\b", re.I)
_MANDATE = re.compile(r"\b(?:shall|must|(?:is|are)\s+required\s+to|(?:is|are)\s+to\b(?!\s+be\s+noted)|has\s+to|have\s+to|needs?\s+to|obliged\s+to|responsible\s+for|(?:is|are)\s+only\s+(?:allowed|permitted))\b", re.I)
_RECOMMEND = re.compile(r"\bshould\b|\bought\s+to\b|\b(?:is|are)\s+(?:advised|urged|expected)\s+to\b|\bmay\s+not\s+exceed\b|\b(?:is|are)\s+encouraged\b|\brecommended\b", re.I)
_PENALTY = re.compile(r"\bpenalt|\bfine[sd]?\b|\bsanction|\brevo(?:ke|cation)\b|\bmonetary\s+penalt", re.I)
_ACTOR = re.compile(r"^(?:the\s+|each\s+|every\s+|all\s+)?(.{3,70}?)\s+(?:shall|must|should)\b", re.I)


def split_clauses(text: str) -> list[tuple[str, str]]:
    clauses: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        m = _CLAUSE.match(line)
        if m and (m.group(1).count(".") or m.group(1).isdigit() or m.group(1)[0].isalpha()):
            clauses.append((m.group(1), [m.group(2).strip()]))
        elif clauses:
            clauses[-1][1].append(line.strip())
        else:
            clauses.append(("0", [line.strip()]))
    return [(ref, " ".join(parts)) for ref, parts in clauses]


def _sentences(s: str) -> list[str]:
    return [x.strip() for x in re.split(r"(?<=[.;])\s+(?=[A-Z(])", s) if x.strip()]


def extract_obligations(text: str, reg: dict) -> list[dict]:
    """reg = {code, version, jurisdiction, effectiveDate, entityTypes}."""
    obls = []
    for ref, body in split_clauses(text):
        for i, sent in enumerate(_sentences(body), 1):
            if _PROHIB.search(sent):
                modality, base = "prohibited", 4.0
            elif _MANDATE.search(sent):
                modality, base = "mandatory", 3.0
            elif _RECOMMEND.search(sent):
                modality, base = "recommended", 1.5
            else:
                continue
            topics = T.topics_of(sent) or T.topics_of(body)
            am = _ACTOR.match(sent)
            ret = T.retention(sent)
            deadline = T.deadline_hours(sent)
            freq = T.frequency_days(sent)
            penalty = bool(_PENALTY.search(body))
            sev = min(5.0, base + max((T.TOPIC_WEIGHT.get(t, 0.3) for t in topics), default=0.0) * 0.8 + (0.4 if penalty else 0))
            obls.append({
                "id": f"{reg['code']}@{reg['version']}#{ref}.{i}",
                "regCode": reg["code"], "version": reg["version"], "clause": ref,
                "text": sent, "actor": am.group(1) if am else None, "modality": modality,
                "topics": topics, "deadlineHours": deadline, "frequencyDays": freq,
                "retentionMinHours": ret.get("minHours"), "retentionMaxHours": ret.get("maxHours"),
                "penaltyMentioned": penalty, "severity": round(sev, 2),
                "jurisdiction": reg.get("jurisdiction"), "effectiveDate": reg.get("effectiveDate"),
                "entityTypes": reg.get("entityTypes") or [],
            })
    return obls


def applicability(obl: dict, profile: dict) -> dict:
    """Feature: applicability to *this* bank (jurisdiction + entity type + effective date)."""
    jur = [j.upper() for j in profile.get("jurisdictions") or []]
    if obl.get("jurisdiction") and jur and obl["jurisdiction"].upper() not in jur:
        return {"applicable": False, "reason": f"jurisdiction {obl['jurisdiction']} not in bank profile {jur}"}
    ets = [e.lower() for e in obl.get("entityTypes") or []]
    et = (profile.get("entityType") or "").lower()
    if ets and et and "all" not in ets and et not in ets:
        return {"applicable": False, "reason": f"applies to {ets}, bank is '{et}'"}
    eff = obl.get("effectiveDate")
    if eff:
        try:
            d = date.fromisoformat(eff)
            if d > date.today():
                return {"applicable": True, "reason": f"upcoming - effective {eff}", "upcoming": True, "daysToEffective": (d - date.today()).days}
        except ValueError:
            pass
    return {"applicable": True, "reason": "in scope"}
