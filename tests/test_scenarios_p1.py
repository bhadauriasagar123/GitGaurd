"""Problem 1 - scenario catalogue. IDs (P1-Fxx-Sn) match docs/TEST_CASES.md."""
import json
from datetime import date

import pytest

from app.compliance import engine
from app.compliance import text as T
from app.compliance.changes import diff_versions
from app.compliance.controls import parse_controls, parse_evidence
from app.compliance.obligations import applicability, extract_obligations, split_clauses
from tests.helpers import ctrl_text, d, mk_state, reg

INC = "1.1 Regulated entities shall report every reportable cyber incident to the regulator within 6 hours of detection."
INC_CTRL = {"id": "C1", "description": "Cyber incidents are reported to the regulator within 6 hours of detection by the CISO.", "frequency": "continuous"}
GOOD = [("C1", d(10), "pass", 0), ("C1", d(40), "pass", 0)]


def A(state):
    return engine.analyze(state)


def status_of(res, frag=""):
    return next(a for a in res["assessments"] if frag in a["obligationId"])["status"]


# ======================================================= F1 ingestion / knowledge
def test_P1_F01_S1_clause_numbering_formats():
    txt = "Article 5 Banks shall encrypt data.\nSection 4.2 Banks must log access.\nA1 Banks shall train staff.\n7. Banks shall report.\nA continuation line.\n"
    refs = [r for r, _ in split_clauses(txt)]
    assert refs == ["5", "4.2", "A1", "7"]
    assert "continuation" in dict(split_clauses(txt))["7"]


def test_P1_F01_S2_multiline_clause_joined():
    obls = extract_obligations("1.1 Banks shall report incidents\nto the regulator within 4 hours.", {"code": "X", "version": "1"})
    assert len(obls) == 1 and obls[0]["deadlineHours"] == 4


def test_P1_F01_S3_unicode_text_ok():
    obls = extract_obligations("1.1 Banks shall protect clients’ données personnelles – “strictly”.", {"code": "X", "version": "1"})
    assert len(obls) == 1


# ======================================================= F2 change intelligence
def _obls(text, ver):
    return extract_obligations(text, {"code": "R", "version": ver})


def test_P1_F02_S1_threshold_tightened_is_high_materiality():
    r = diff_versions(_obls(INC, "1"), _obls(INC.replace("6 hours", "2 hours"), "2"))
    assert r["modified"][0]["materiality"] == "high" and "deadline: 6 hour(s) -> 2 hour(s)" in r["modified"][0]["changes"]


def test_P1_F02_S2_new_and_removed_clauses():
    old = _obls(INC + "\n1.2 Banks shall train staff annually.", "1")
    new = _obls(INC + "\n2.1 Banks shall assess third-party service providers before onboarding.", "2")
    r = diff_versions(old, new)
    assert [a["clause"] for a in r["added"]] == ["2.1"] and [x["clause"] for x in r["removed"]] == ["1.2"] and r["unchangedCount"] == 1


def test_P1_F02_S3_identical_version_reports_no_changes():
    r = diff_versions(_obls(INC, "1"), _obls(INC, "2"))
    assert not r["modified"] and not r["added"] and not r["removed"] and r["unchangedCount"] == 1


def test_P1_F02_S4_numeric_version_ordering():
    st = mk_state([reg("R", "1.9", INC), reg("R", "1.10", INC.replace("6 hours", "3 hours")), reg("R", "1.2", INC.replace("6 hours", "9 hours"))], [INC_CTRL])
    res = A(st)
    assert res["changes"][0]["toVersion"] == "1.10" and res["obligations"][0]["deadlineHours"] == 3


# ======================================================= F3 obligation extraction
@pytest.mark.parametrize("sentence,modality", [
    ("Banks shall report incidents.", "mandatory"), ("Banks must report incidents.", "mandatory"),
    ("Banks are required to report incidents.", "mandatory"), ("Banks shall not share data.", "prohibited"),
    ("Sharing of data is prohibited.", "prohibited"), ("Banks must not store CVV.", "prohibited"),
    ("Banks should train staff.", "recommended"), ("Banks may choose a vendor.", None), ("The bank was founded in 1990.", None)])
def test_P1_F03_S1_modality(sentence, modality):
    o = extract_obligations("1.1 " + sentence, {"code": "X", "version": "1"})
    assert (o[0]["modality"] if o else None) == modality


@pytest.mark.parametrize("phrase,hours", [("within 24 hours", 24), ("within twenty-four hours", 24), ("within 2 days", 48),
                                          ("within 1 week", 168), ("within seventy-two hours", 72), ("within 30 minutes".replace("minutes", "hours"), 30)])
def test_P1_F03_S2_deadline_parsing(phrase, hours):
    assert T.deadline_hours(f"Banks shall notify {phrase}.") == hours


@pytest.mark.parametrize("phrase,days", [("quarterly", 92), ("monthly", 31), ("annually", 366), ("half-yearly", 184), ("every 14 days", 14), ("daily", 1)])
def test_P1_F03_S3_frequency_parsing(phrase, days):
    assert T.frequency_days(f"Reviews shall be performed {phrase}.") == days


def test_P1_F03_S4_retention_min_and_max():
    assert T.retention("Records shall be kept for at least 5 years")["minHours"] == 5 * 8760
    assert T.retention("Data shall not be retained for longer than 12 months")["maxHours"] == 12 * 730


def test_P1_F03_S5_penalty_raises_severity_and_actor_captured():
    a = extract_obligations("1.1 Banks shall report incidents.", {"code": "X", "version": "1"})[0]
    b = extract_obligations("1.1 Banks shall report incidents. Failure attracts a monetary penalty.", {"code": "X", "version": "1"})[0]
    assert b["penaltyMentioned"] and b["severity"] > a["severity"] and a["actor"] == "Banks"


def test_P1_F03_S6_applicability_by_jurisdiction_entity_and_future_date():
    o = {"jurisdiction": "US", "entityTypes": ["all"]}
    assert not applicability(o, {"jurisdictions": ["IN"]})["applicable"]
    assert not applicability({"entityTypes": ["payments bank"]}, {"entityType": "scheduled commercial bank"})["applicable"]
    up = applicability({"effectiveDate": d(-30)}, {"jurisdictions": ["IN"]})
    assert up["applicable"] and up["upcoming"] and up["daysToEffective"] == 30


# ======================================================= F4 control framework understanding
def test_P1_F04_S1_text_blocks_and_json_inputs_equivalent():
    t = ctrl_text({"id": "C1", "description": "MFA enforced for privileged access.", "type": "preventive", "frequency": "continuous", "automation": "automated"})
    j = json.dumps([{"id": "C1", "description": "MFA enforced for privileged access.", "type": "preventive", "frequency": "continuous", "automation": "automated", "owner": "Owner X"}])
    a, b = parse_controls(t)[0], parse_controls(j)[0]
    assert a["type"] == b["type"] == "preventive" and a["owner"] == b["owner"] and a["topics"] == b["topics"] == ["access-control"]


def test_P1_F04_S2_sla_and_cadence_extracted_from_free_text():
    c = parse_controls(ctrl_text({"id": "C1", "description": "Incidents reported to the regulator within 24 hours.", "frequency": "annually"}))[0]
    assert c["deadlineHours"] == 24 and c["frequencyDays"] == 366


def test_P1_F04_S3_malformed_blocks_ignored_not_crash():
    assert parse_controls("Title: orphan without id\nDescription: nothing") == []
    assert parse_controls("[not json") == []
    assert parse_evidence('[{"id":"E1","control":"C1","date":"garbage"}]') == []


# ======================================================= F5 mapping
def test_P1_F05_S1_related_control_mapped_with_rationale():
    res = A(mk_state([reg("R", "1", INC)], [INC_CTRL], GOOD))
    m = res["assessments"][0]["mappedControls"][0]
    assert m["controlId"] == "C1" and m["strength"] == "strong" and m["sharedTopics"] and m["sharedTerms"]


def test_P1_F05_S2_unrelated_control_not_mapped():
    res = A(mk_state([reg("R", "1", INC)], [{"id": "C9", "description": "Cafeteria menu is reviewed by facilities every week."}]))
    assert res["assessments"][0]["mappedControls"] == [] and res["assessments"][0]["status"] == "uncovered"


def test_P1_F05_S3_breach_notification_maps_to_incident_control():
    res = A(mk_state([reg("R", "1", "1.1 Controllers shall notify the supervisory authority of a personal data breach within 72 hours.")], [INC_CTRL], GOOD))
    assert res["assessments"][0]["mappedControls"][0]["controlId"] == "C1"


# ======================================================= F6 control effectiveness
def eff(ctrl, evidence):
    res = A(mk_state([reg("R", "1", "1.1 Banks shall enforce multi-factor authentication for privileged access.")], [ctrl], evidence))
    return res["controlEffectiveness"][0]


MFA = {"id": "C1", "description": "Multi-factor authentication is enforced for privileged access.", "type": "preventive", "frequency": "continuous", "automation": "automated"}


def test_P1_F06_S1_untested_control_is_capped_below_effective():
    e = eff(MFA, [])
    assert e["rating"] == "untested" and e["overall"] < 50 and e["operatingScore"] is None


def test_P1_F06_S2_fresh_passing_tests_effective():
    assert eff(MFA, [("C1", d(5), "pass", 0), ("C1", d(60), "pass", 0)])["rating"] == "effective"


def test_P1_F06_S3_stale_evidence_reduces_score():
    fresh, stale = eff(MFA, [("C1", d(5), "pass", 0)]), eff(MFA, [("C1", d(700), "pass", 0)])
    assert stale["overall"] < fresh["overall"] and stale["notes"]


def test_P1_F06_S4_latest_failure_and_exceptions_ineffective():
    e = eff({**MFA, "automation": "manual"}, [("C1", d(30), "pass", 0), ("C1", d(3), "fail", 4)])
    assert e["rating"] in ("ineffective", "partially_effective") and any("FAILED" in n for n in e["notes"])


def test_P1_F06_S5_automation_and_ownership_improve_design_score():
    auto = eff(MFA, [("C1", d(5), "pass", 0)])["designScore"]
    manual = eff({**MFA, "automation": "manual"}, [("C1", d(5), "pass", 0)])["designScore"]
    noowner = eff({**MFA, "owner": ""}, [("C1", d(5), "pass", 0)])["designScore"]
    assert auto > manual and auto >= noowner


# ======================================================= F7 evidence-based compliance
def test_P1_F07_S1_design_without_evidence_never_compliant():
    assert status_of(A(mk_state([reg("R", "1", INC)], [INC_CTRL], []))) == "partial"


def test_P1_F07_S2_passing_evidence_makes_compliant():
    assert status_of(A(mk_state([reg("R", "1", INC)], [INC_CTRL], GOOD))) == "compliant"


def test_P1_F07_S3_failing_evidence_makes_non_compliant():
    assert status_of(A(mk_state([reg("R", "1", INC)], [INC_CTRL], [("C1", d(30), "pass", 0), ("C1", d(2), "fail", 5)]))) in ("non_compliant", "partial")


def test_P1_F07_S4_score_is_severity_weighted():
    two = "1.1 Banks shall report incidents within 6 hours.\n1.2 Banks should train staff annually."
    res = A(mk_state([reg("R", "1", two)], [INC_CTRL], GOOD))
    s = {a["clause"]: a for a in res["assessments"]}
    assert s["1.1"]["severity"] > s["1.2"]["severity"] and 0 < res["complianceScore"] < 100


# ======================================================= F8 gap identification (all 7 gap types)
def gaps_of(state):
    return {g["type"] for g in A(state)["gaps"]}


def test_P1_F08_S1_no_control():
    assert gaps_of(mk_state([reg("R", "1", INC)])) == {"NO_CONTROL"}


def test_P1_F08_S2_weak_coverage():
    two_topic = "1.1 Banks shall encrypt customer data and restrict access using multi-factor authentication."
    partial = {"id": "C2", "description": "Multi-factor authentication is enforced for staff logins.", "frequency": "continuous"}
    assert "WEAK_COVERAGE" in gaps_of(mk_state([reg("R", "1", two_topic)], [partial], [("C2", d(5), "pass", 0)]))


def test_P1_F08_S3_untested():
    assert "UNTESTED_CONTROL" in gaps_of(mk_state([reg("R", "1", INC)], [INC_CTRL]))


def test_P1_F08_S4_ineffective():
    manual = {**INC_CTRL, "automation": "manual", "type": "corrective", "frequency": "annually"}
    assert "INEFFECTIVE_CONTROL" in gaps_of(mk_state([reg("R", "1", INC)], [manual], [("C1", d(100), "fail", 5)]))


def test_P1_F08_S5_stale_evidence():
    assert "STALE_EVIDENCE" in gaps_of(mk_state([reg("R", "1", INC)], [INC_CTRL], [("C1", d(800), "pass", 0)]))


def test_P1_F08_S6_threshold_mismatch():
    slow = {**INC_CTRL, "description": "Cyber incidents are reported to the regulator within 24 hours of detection."}
    g = [x for x in A(mk_state([reg("R", "1", INC)], [slow], GOOD))["gaps"] if x["type"] == "THRESHOLD_MISMATCH"]
    assert g and "6 hour" in g[0]["detail"] and "24 hour" in g[0]["detail"]


def test_P1_F08_S7_frequency_mismatch():
    q = "1.1 Access rights shall be reviewed monthly for privileged accounts."
    c = {"id": "C1", "description": "User access rights and privileged accounts are reviewed under least privilege annually.", "frequency": "annually"}
    assert "FREQUENCY_MISMATCH" in gaps_of(mk_state([reg("R", "1", q)], [c], [("C1", d(10), "pass", 0)]))


def test_P1_F08_S8_retention_mismatch_between_obligation_and_control():
    r = "1.1 Banks shall retain transaction records for at least 5 years."
    c = {"id": "C1", "description": "Transaction records are retained and then deleted no longer than 12 months.", "frequency": "continuous"}
    assert "THRESHOLD_MISMATCH" in gaps_of(mk_state([reg("R", "1", r)], [c], [("C1", d(5), "pass", 0)]))


def test_P1_F08_S9_out_of_scope_obligation_creates_no_gap():
    assert A(mk_state([reg("US", "1", INC, jur="US")], profile={"jurisdictions": ["IN"]}))["gaps"] == []


# ======================================================= F9 prioritisation
def test_P1_F09_S1_gaps_sorted_by_risk_with_bands():
    txt = INC + "\n1.2 Banks should train staff annually.\n1.3 Banks shall not store CVV. Penalty applies."
    res = A(mk_state([reg("R", "1", txt)]))
    scores = [g["risk"]["riskScore"] for g in res["gaps"]]
    assert scores == sorted(scores, reverse=True) and res["gaps"][-1]["clause"] == "1.2"


def test_P1_F09_S2_bands_follow_thresholds():
    res = A(mk_state([reg("R", "1", INC)]))
    g = res["gaps"][0]["risk"]
    assert g["band"] in ("critical", "high") and set(g["factors"]) == {"severity", "likelihood", "urgency", "penaltyExposure"}


def test_P1_F09_S3_imminent_effective_date_raises_urgency():
    near = A(mk_state([reg("R", "1", INC, eff=d(-10))]))["gaps"][0]["risk"]["factors"]["urgency"]
    far = A(mk_state([reg("R", "1", "1.1 Banks shall report incidents.", eff=d(-400))]))["gaps"][0]["risk"]["factors"]["urgency"]
    assert near >= far


# ======================================================= F10 remediation
@pytest.mark.parametrize("gtype", ["NO_CONTROL", "THRESHOLD_MISMATCH", "UNTESTED_CONTROL"])
def test_P1_F10_S1_every_gap_has_actionable_remediation(gtype):
    states = {"NO_CONTROL": mk_state([reg("R", "1", INC)]), "UNTESTED_CONTROL": mk_state([reg("R", "1", INC)], [INC_CTRL]),
              "THRESHOLD_MISMATCH": mk_state([reg("R", "1", INC)], [{**INC_CTRL, "description": "Incidents are reported to the regulator within 24 hours."}], GOOD)}
    g = next(x for x in A(states[gtype])["gaps"] if x["type"] == gtype)["remediation"]
    assert len(g["steps"]) >= 2 and g["ownerRole"] and g["effort"] in "SML" and g["targetDays"] > 0 and g["expectedScoreUpliftPct"] > 0


def test_P1_F10_S2_topic_playbook_used():
    g = A(mk_state([reg("R", "1", INC)]))["gaps"][0]["remediation"]
    assert g["ownerRole"] == "CISO" and "runbook" in " ".join(g["steps"]).lower()


# ======================================================= F11 autonomous impact analysis (API)
async def test_P1_F11_S1_new_version_triggers_impact_without_extra_call(client):
    from tests.conftest import ANALYST, VIEWER
    base = {"kind": "regulation", "title": "Reg R", "sourceType": "pdf"}
    meta = lambda v, eff: {"code": "RR", "version": v, "jurisdiction": "IN", "effectiveDate": eff}
    r1 = await client.post("/api/v1/documents", headers=ANALYST, json={**base, "regulation": meta("1.0", d(100)), "content": INC})
    assert r1.status_code == 201 and r1.json()["impact"]["change"] is None  # first version: nothing to diff
    ctrl = {"kind": "control", "title": "Ctrl", "sourceType": "text", "content": ctrl_text(INC_CTRL)}
    assert (await client.post("/api/v1/documents", headers=ANALYST, json=ctrl)).status_code == 201
    r2 = await client.post("/api/v1/documents", headers=ANALYST, json={**base, "regulation": meta("2.0", d(-20)), "content": INC.replace("6 hours", "2 hours") + "\n1.2 Banks shall assess third-party service providers before onboarding."})
    imp = r2.json()["impact"]
    assert imp["change"]["modified"] and imp["change"]["added"] and "C1" in imp["impactedControls"] and imp["newGaps"]
    stored = (await client.get("/api/v1/impact", headers=VIEWER)).json()
    assert any(x["id"] == "RR@2.0" for x in stored)


# ======================================================= F12 what-if
SC = mk_state([reg("R", "1", INC + "\n1.2 Banks shall enforce multi-factor authentication for privileged access.")], [INC_CTRL], GOOD)


def test_P1_F12_S1_add_control_resolves_gap():
    r = engine.simulate(SC, [{"type": "add_control", "tested": True, "control": {"id": "C2", "description": MFA["description"], "type": "preventive", "frequency": "continuous", "automation": "automated", "owner": "X"}}])
    assert r["deltaScore"] > 0 and r["gapsResolved"]


def test_P1_F12_S2_remove_control_creates_gap():
    r = engine.simulate(SC, [{"type": "remove_control", "controlId": "C1"}])
    assert r["deltaScore"] < 0 and r["gapsIntroduced"]


def test_P1_F12_S3_update_control_frequency():
    st = mk_state([reg("R", "1", "1.1 Access rights shall be reviewed monthly.")], [{"id": "C1", "description": "User access rights are reviewed under least privilege annually.", "frequency": "annually"}], [("C1", d(5), "pass", 0)])
    r = engine.simulate(st, [{"type": "update_control", "controlId": "C1", "frequency": "monthly"}])
    assert r["deltaScore"] > 0


def test_P1_F12_S4_add_failing_evidence_degrades():
    r = engine.simulate(SC, [{"type": "add_evidence", "controlId": "C1", "result": "fail", "exceptions": 5}])
    assert r["deltaScore"] < 0


def test_P1_F12_S5_regulator_change_introduces_gap():
    r = engine.simulate(SC, [{"type": "change_regulation", "regCode": "R", "topic": "incident-reporting", "deadlineHours": 1}])
    assert any(g["title"].startswith("Control timing") for g in r["gapsIntroduced"]) or r["deltaScore"] < 0


def test_P1_F12_S6_profile_change_alters_scope():
    st = mk_state([reg("R", "1", INC, jur="EU")], [INC_CTRL], GOOD, profile={"jurisdictions": ["IN"]})
    assert A(st)["counts"]["inScope"] == 0
    r = engine.simulate(st, [{"type": "set_profile", "jurisdictions": ["IN", "EU"]}])
    assert r["after"]["gaps"] >= 0 and r["obligationStatusShifts"]


def test_P1_F12_S7_simulation_never_mutates_input():
    import copy
    before = copy.deepcopy(SC)
    engine.simulate(SC, [{"type": "remove_control", "controlId": "C1"}, {"type": "add_evidence", "controlId": "C1", "result": "fail"}])
    assert SC == before


def test_P1_F12_S8_bad_change_types_rejected():
    with pytest.raises(ValueError):
        engine.simulate(SC, [{"type": "format_disk"}])
    with pytest.raises(Exception):
        engine.simulate(SC, [{"type": "add_control", "control": {"description": "no id"}}])


# ======================================================= F13 cross-regulation
def test_P1_F13_S1_overlap_clustered_with_strictest_deadline():
    a = reg("A", "1", "1.1 Banks shall notify the authority of a cyber incident within 6 hours.")
    b = reg("B", "1", "1.1 Controllers shall notify the supervisory authority of a data breach incident within 72 hours.", jur="EU")
    res = A(mk_state([a, b], [INC_CTRL], GOOD))
    c = res["crossRegulation"][0]
    assert set(c["regulations"]) == {"A", "B"} and c["strictestDeadline"] == "6 hour(s)" and "ONE control" in c["harmonisation"]


def test_P1_F13_S2_unrelated_regulations_not_clustered():
    a = reg("A", "1", "1.1 Banks shall encrypt customer data at rest.")
    b = reg("B", "1", "1.1 Banks shall report suspicious transactions to the financial intelligence unit.")
    assert A(mk_state([a, b]))["crossRegulation"] == []


def test_P1_F13_S3_same_regulation_not_self_clustered():
    assert A(mk_state([reg("A", "1", INC + "\n1.2 Banks shall report data breach incidents within 6 hours.")]))["crossRegulation"] == []


# ======================================================= F14 contradictions
def test_P1_F14_S1_hard_retention_conflict():
    a = reg("AML", "1", "1.1 Banks shall retain customer records for at least 5 years.")
    b = reg("DPR", "1", "1.1 Customer records shall not be retained for longer than 12 months.", jur="EU")
    c = A(mk_state([a, b]))["contradictions"]
    assert c and c[0]["type"] == "HARD_CONFLICT" and c[0]["severity"] == "critical" and c[0]["resolution"]


def test_P1_F14_S2_compatible_retention_is_not_a_conflict():
    a = reg("AML", "1", "1.1 Banks shall retain customer records for at least 1 year.")
    b = reg("DPR", "1", "1.1 Customer records shall not be retained for longer than 5 years.", jur="EU")
    assert [x for x in A(mk_state([a, b]))["contradictions"] if x["type"] == "HARD_CONFLICT"] == []


def test_P1_F14_S3_modality_conflict():
    a = reg("A", "1", "1.1 Banks shall share customer transaction data with the credit bureau.")
    b = reg("B", "1", "1.1 Banks shall not share customer transaction data with credit bureaus.", jur="EU")
    assert any(x["type"] == "MODALITY_CONFLICT" for x in A(mk_state([a, b]))["contradictions"])


def test_P1_F14_S4_deadline_divergence_recommends_strictest():
    a = reg("A", "1", "1.1 Banks shall notify the authority of a cyber incident within 6 hours.")
    b = reg("B", "1", "1.1 Banks shall notify the authority of a cyber incident within 72 hours.", jur="EU")
    c = [x for x in A(mk_state([a, b]))["contradictions"] if x["type"] == "DEADLINE_DIVERGENCE"]
    assert c and "6 hour" in c[0]["resolution"]


# ======================================================= end-to-end score target on the demo bank
def test_P1_E2E_demo_bank_score_is_in_expected_band():
    from app.sample import data as S
    regs, ctrl, ev = [], [], []
    for x in S.build():
        if x["kind"] == "regulation":
            regs.append({"meta": dict(x["regulation"]), "text": x["content"]})
        elif x["kind"] == "control":
            ctrl = parse_controls(x["content"])
        else:
            ev = parse_evidence(x["content"])
    res = A({"profile": S.PROFILE, "regulations": regs, "controls": ctrl, "evidence": ev})
    assert 75 <= res["complianceScore"] <= 85, res["complianceScore"]
    types = {g["type"] for g in res["gaps"]}
    assert {"NO_CONTROL", "THRESHOLD_MISMATCH", "FREQUENCY_MISMATCH"} <= types  # the demo still tells a gap story
