"""One test per desirable feature of Problem Statement 1 (all 14)."""
from datetime import date

import pytest

from app.compliance import engine
from app.compliance.controls import parse_controls, parse_evidence
from app.compliance.obligations import applicability, extract_obligations
from app.sample import data as S


@pytest.fixture(scope="module")
def state():
    regs, ctrl, ev = [], [], []
    for d in S.build():
        if d["kind"] == "regulation":
            regs.append({"meta": dict(d["regulation"]), "text": d["content"]})
        elif d["kind"] == "control":
            ctrl = parse_controls(d["content"])
        else:
            ev = parse_evidence(d["content"])
    return {"profile": S.PROFILE, "regulations": regs, "controls": ctrl, "evidence": ev}


@pytest.fixture(scope="module")
def result(state):
    return engine.analyze(state)


def test_f01_knowledge_ingestion(state):
    assert len(state["regulations"]) == 5 and len(state["controls"]) == 13 and len(state["evidence"]) == 20


def test_f02_regulatory_change_intelligence(result):
    ch = next(c for c in result["changes"] if c["regCode"] == "IN-CYBER")
    mod = {m["new"]["clause"]: m for m in ch["modified"]}
    assert any("deadline: 6 hour(s) -> 2 hour(s)" in x for x in mod["1.1"]["changes"])
    assert [a["clause"] for a in ch["added"]] == ["5.1"] and mod["1.1"]["materiality"] == "high"


def test_f03_obligation_extraction():
    obls = extract_obligations("1.1 Banks shall report incidents within 24 hours.\n1.2 Banks must not store CVV data.\n1.3 Banks should train staff annually.\n1.4 Background paragraph without duty.",
                               {"code": "X", "version": "1"})
    kinds = {o["clause"]: o for o in obls}
    assert kinds["1.1"]["modality"] == "mandatory" and kinds["1.1"]["deadlineHours"] == 24
    assert kinds["1.2"]["modality"] == "prohibited" and kinds["1.3"]["modality"] == "recommended" and "1.4" not in kinds


def test_applicability_filters_out_of_scope(result):
    assert any(o["regCode"] == "US-GLBA" and not o["applicability"]["applicable"] for o in result["obligations"])
    assert applicability({"jurisdiction": "EU", "entityTypes": ["all"]}, {"jurisdictions": ["IN"]})["applicable"] is False


def test_f04_control_framework_understanding(state):
    c = {x["id"]: x for x in state["controls"]}["C-02"]
    assert c["deadlineHours"] == 24 and c["type"] == "corrective" and c["owner"] == "CISO"


def test_f05_regulation_to_control_mapping(result):
    m = {a["obligationId"]: a for a in result["assessments"]}["IN-CYBER@2.0#2.1.1"]
    assert m["mappedControls"][0]["controlId"] == "C-03" and m["mappedControls"][0]["rationale"]


def test_f06_control_effectiveness(result):
    e = {x["controlId"]: x for x in result["controlEffectiveness"]}
    assert e["C-07"]["rating"] == "partially_effective" and "3 exception(s) in recent tests" in e["C-07"]["notes"]
    assert e["C-10"]["rating"] == "effective" and e["C-05"]["rating"] == "effective"


def test_f07_evidence_based_assessment(result):
    st = {a["obligationId"]: a["status"] for a in result["assessments"]}
    assert st["IN-AML@1.0#1.1.1"] == "compliant" and st["IN-CYBER@2.0#4.1.1"] == "partial"  # exceptions in recent tests => not fully compliant


def test_f08_gap_identification(result):
    types = {g["type"] for g in result["gaps"]}
    assert {"NO_CONTROL", "THRESHOLD_MISMATCH", "FREQUENCY_MISMATCH", "STALE_EVIDENCE"} <= types


def test_f09_risk_prioritisation(result):
    scores = [g["risk"]["riskScore"] for g in result["gaps"]]
    assert scores == sorted(scores, reverse=True) and all(g["risk"]["factors"] for g in result["gaps"])


def test_f10_remediation(result):
    g = result["gaps"][0]["remediation"]
    assert g["steps"] and g["ownerRole"] and g["targetDays"] > 0 and g["successCriteria"]


def test_f11_autonomous_impact_analysis_after_regulation_change(state):
    base = {**state, "regulations": [r for r in state["regulations"] if r["meta"]["version"] != "2.0"]}
    before, after = engine.analyze(base), engine.analyze(state)
    assert after["complianceScore"] != before["complianceScore"]
    assert {g["id"] for g in after["gaps"]} - {g["id"] for g in before["gaps"]}  # new gaps surfaced automatically


def test_f12_what_if_simulation_improves_and_is_pure(state):
    n_before = len(state["controls"])
    r = engine.simulate(state, [{"type": "add_control", "tested": True, "control": {
        "id": "C-99", "title": "Marketing consent management", "type": "preventive", "automation": "automated", "owner": "DPO",
        "frequency": "continuous", "description": "Explicit consent from data subjects is obtained before processing personal data for marketing purposes."}}])
    assert r["deltaScore"] > 0 and r["gapsResolved"]
    assert len(state["controls"]) == n_before  # original state untouched
    worse = engine.simulate(state, [{"type": "change_regulation", "regCode": "IN-CYBER", "topic": "incident-reporting", "deadlineHours": 1}])
    assert worse["deltaScore"] <= 0 or worse["gapsIntroduced"]


def test_f13_cross_regulation_intelligence(result):
    assert any({"EU-DPR", "IN-CYBER"} <= set(c["regulations"]) and c["strictestDeadline"] for c in result["crossRegulation"])


def test_f14_contradiction_detection(result):
    types = {c["type"] for c in result["contradictions"]}
    assert "HARD_CONFLICT" in types and "DEADLINE_DIVERGENCE" in types
    hard = next(c for c in result["contradictions"] if c["type"] == "HARD_CONFLICT")
    assert {b["regCode"] for b in hard["between"]} == {"IN-AML", "EU-DPR"}


def test_unknown_whatif_type_rejected(state):
    with pytest.raises(ValueError):
        engine.simulate(state, [{"type": "nope"}])
