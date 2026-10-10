"""Features 8-10: gap identification, risk-based prioritisation, remediation recommendations."""
from __future__ import annotations

from datetime import date

from app.compliance import text as T
from app.compliance.mapping import MAPPED

LIKELIHOOD = {"NO_CONTROL": 5, "INEFFECTIVE_CONTROL": 4, "THRESHOLD_MISMATCH": 4, "FREQUENCY_MISMATCH": 3,
              "WEAK_COVERAGE": 3, "UNTESTED_CONTROL": 3, "STALE_EVIDENCE": 2}
TITLE = {"NO_CONTROL": "No control addresses this obligation", "WEAK_COVERAGE": "Only weak/partial control coverage",
         "INEFFECTIVE_CONTROL": "Mapped control is ineffective", "UNTESTED_CONTROL": "Mapped control has no test evidence",
         "STALE_EVIDENCE": "Control evidence is stale or showing failures", "THRESHOLD_MISMATCH": "Control timing is looser than the obligation",
         "FREQUENCY_MISMATCH": "Control runs less often than the obligation requires"}


def _gap(obl, gtype, detail, controls=None, evidence=None):
    return {"id": f"GAP:{obl['id']}:{gtype}", "obligationId": obl["id"], "regCode": obl["regCode"], "clause": obl["clause"],
            "type": gtype, "title": TITLE[gtype], "detail": detail, "obligation": obl["text"], "topics": obl["topics"],
            "controls": controls or [], "evidence": evidence or []}


def assess_obligation(obl: dict, maps: list[dict], controls: dict[str, dict], eff: dict[str, dict]) -> dict:
    """Return {status, gaps, supportingControls}. Status: compliant | partial | non_compliant | uncovered."""
    strong = [m for m in maps if m["strength"] == "strong"]
    gaps: list[dict] = []
    if not maps:
        gaps.append(_gap(obl, "NO_CONTROL", "No control in the framework maps to this obligation."))
        return {"status": "uncovered", "gaps": gaps, "supportingControls": []}
    if not strong:
        gaps.append(_gap(obl, "WEAK_COVERAGE", f"Best match {maps[0]['controlId']} scores only {maps[0]['score']}; wording/scope does not clearly cover the obligation.", [maps[0]["controlId"]]))
    best = max(strong or maps, key=lambda m: m["score"] * 100 + eff[m["controlId"]]["overall"] * 0.2)  # relevance first, effectiveness breaks ties
    c, e = controls[best["controlId"]], eff[best["controlId"]]
    status = "compliant"
    if e["rating"] == "untested":
        gaps.append(_gap(obl, "UNTESTED_CONTROL", f"{c['id']} is designed but has no test evidence.", [c["id"]])); status = "partial"
    elif e["rating"] == "ineffective":
        gaps.append(_gap(obl, "INEFFECTIVE_CONTROL", f"{c['id']} scored {e['overall']}/100 ({'; '.join(e['notes']) or 'poor design/operation'}).", [c["id"]])); status = "non_compliant"
    elif e["rating"] == "partially_effective":
        gaps.append(_gap(obl, "STALE_EVIDENCE", f"{c['id']} scored {e['overall']}/100 ({'; '.join(e['notes']) or 'partial'}).", [c["id"]])); status = "partial"
    elif e["freshness"] is not None and e["freshness"] < 100:
        gaps.append(_gap(obl, "STALE_EVIDENCE", f"{c['id']}: {'; '.join(e['notes'])}", [c["id"]])); status = "partial"
    dl = [controls[m["controlId"]] for m in (strong or maps) if controls[m["controlId"]].get("deadlineHours")]
    if obl.get("deadlineHours") and dl and all(x["deadlineHours"] > obl["deadlineHours"] * 1.001 for x in dl):
        w = min(dl, key=lambda x: x["deadlineHours"])
        gaps.append(_gap(obl, "THRESHOLD_MISMATCH", f"Obligation requires within {T.humanize_hours(obl['deadlineHours'])}; best-matching control {w['id']} allows {T.humanize_hours(w['deadlineHours'])}.", [w["id"]]))
        status = "non_compliant"
    if obl.get("frequencyDays") and c.get("frequencyDays") and c["frequencyDays"] > obl["frequencyDays"] * 1.05:
        gaps.append(_gap(obl, "FREQUENCY_MISMATCH", f"Obligation requires {obl['frequencyDays']:g}-day cadence; control {c['id']} runs every {c['frequencyDays']:g} days.", [c["id"]]))
        status = "non_compliant" if status == "compliant" else status
    if obl.get("retentionMinHours") and c.get("retentionMaxHours") and c["retentionMaxHours"] < obl["retentionMinHours"]:
        gaps.append(_gap(obl, "THRESHOLD_MISMATCH", f"Retention: obligation needs >= {T.humanize_hours(obl['retentionMinHours'])}, control {c['id']} deletes after {T.humanize_hours(c['retentionMaxHours'])}.", [c["id"]]))
        status = "non_compliant"
    if not strong and status == "compliant":
        status = "partial"
    return {"status": status, "gaps": gaps, "supportingControls": [m["controlId"] for m in (strong or maps)], "bestControl": c["id"]}


def prioritize(gap: dict, obl: dict, today: date) -> dict:
    """Risk = severity(1-5) x likelihood(1-5) / 25 x urgency, scaled to 0-100 with an explainable breakdown."""
    sev = obl["severity"]
    lik = LIKELIHOOD[gap["type"]]
    urgency = 1.0
    eff = obl.get("effectiveDate")
    if eff:
        try:
            days = (date.fromisoformat(eff) - today).days
            urgency = 1.0 if days <= 30 else 0.9 if days <= 90 else 0.75
        except ValueError:
            pass
    if obl.get("deadlineHours") and obl["deadlineHours"] <= 24:
        urgency = min(1.0, urgency + 0.1)
    score = round(min(100.0, sev * lik / 25 * urgency * 100), 1)
    band = "critical" if score >= 70 else "high" if score >= 45 else "medium" if score >= 25 else "low"
    return {"riskScore": score, "band": band, "factors": {"severity": sev, "likelihood": lik, "urgency": round(urgency, 2),
                                                          "penaltyExposure": obl["penaltyMentioned"]}}


PLAYBOOK = {
    "incident-reporting": ("Build a regulator-notification runbook with automated clock start at detection; add 24x7 on-call escalation and pre-approved report templates.", "CISO", 21),
    "breach-notification": ("Implement breach triage + notification workflow (legal review, customer comms templates) with SLA timers and quarterly tabletop tests.", "DPO / CISO", 28),
    "access-control": ("Enforce MFA and least-privilege via IAM policy-as-code; schedule automated quarterly access recertification with manager attestation.", "Head of IT Security", 30),
    "encryption": ("Mandate AES-256/TLS1.2+ baselines, centralise keys in HSM/Key Vault with rotation and discovery scans for unencrypted stores.", "Head of Infrastructure", 45),
    "data-retention": ("Define a retention schedule per data class, implement automated retention/erasure jobs and log deletions as evidence.", "Data Governance Lead", 45),
    "logging-monitoring": ("Centralise logs in a SIEM with alert use-cases mapped to the obligation; add log-integrity protection and weekly alert-handling metrics.", "SOC Manager", 30),
    "vendor-risk": ("Introduce tiered third-party due diligence, contractual security/audit clauses and continuous vendor monitoring.", "Head of Procurement / TPRM", 60),
    "business-continuity": ("Define RTO/RPO per critical service, run annual DR failover tests and keep signed test reports as evidence.", "Head of Resilience", 60),
    "vulnerability-mgmt": ("Adopt risk-based patch SLAs (critical <= 7d), continuous scanning and annual independent penetration tests with tracked closure.", "Head of IT Security", 30),
    "customer-consent": ("Centralise consent capture with purpose tagging and a revocation API; audit downstream usage.", "DPO", 45),
    "kyc-aml": ("Strengthen CDD/EDD procedures, automate sanctions screening and tune transaction-monitoring scenarios; document QA sampling.", "Chief Compliance Officer", 45),
    "governance": ("Assign accountable executive, add the requirement to Board risk-committee charter and track via quarterly reporting.", "Company Secretary / CRO", 30),
    "training": ("Create role-based training with completion tracking and annual attestation.", "HR / Compliance", 30),
    "fraud": ("Deploy real-time fraud rules with case management and monthly effectiveness review.", "Head of Fraud Risk", 45),
}
FIX_BY_TYPE = {
    "NO_CONTROL": "Design and implement a NEW control",
    "WEAK_COVERAGE": "Re-scope/extend the nearest control so its wording explicitly covers the obligation",
    "UNTESTED_CONTROL": "Run and document a test of the control",
    "INEFFECTIVE_CONTROL": "Remediate control design/operation and re-test",
    "STALE_EVIDENCE": "Refresh testing to the required cadence and resolve exceptions",
    "THRESHOLD_MISMATCH": "Tighten the control's SLA/threshold to meet the obligation",
    "FREQUENCY_MISMATCH": "Increase control frequency (automate if needed)",
}


def remediation(gap: dict, obl: dict, total_weight: float) -> dict:
    topic = next((t for t in obl["topics"] if t in PLAYBOOK), None)
    pb = PLAYBOOK.get(topic)
    steps = [FIX_BY_TYPE[gap["type"]] + f" for {obl['regCode']} clause {obl['clause']}."]
    if pb:
        steps.append(pb[0])
    if gap["type"] in ("THRESHOLD_MISMATCH", "FREQUENCY_MISMATCH"):
        steps.append("Update control narrative, SLA monitors and alerting to the new threshold; get owner sign-off.")
    steps.append("Collect and file dated evidence (screenshots/logs/tickets) and schedule a re-test within 30 days.")
    target = pb[2] if pb else 45
    effort = "L" if target >= 60 else "M" if target >= 30 else "S"
    weight = obl["severity"] / total_weight * 100 if total_weight else 0
    return {"summary": steps[0], "steps": steps, "ownerRole": pb[1] if pb else "Control Owner / Compliance",
            "effort": effort, "targetDays": target, "successCriteria": f"Obligation {obl['id']} assessed 'compliant' with passing, in-cadence test evidence.",
            "expectedScoreUpliftPct": round(weight * (1.0 if gap["type"] in ("NO_CONTROL", "INEFFECTIVE_CONTROL", "THRESHOLD_MISMATCH") else 0.5), 2)}
