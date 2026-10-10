"""The hover explanation of the headline score must be exactly consistent with the score itself."""
from app.compliance.engine import score_breakdown
from tests.conftest import ANALYST, VIEWER


async def test_breakdown_points_add_up_to_the_score(client):
    await client.post("/api/v1/sample/load", headers={**ANALYST, "Idempotency-Key": "score-breakdown-01"})
    s = (await client.get("/api/v1/analysis/summary", headers=VIEWER)).json()
    b = s["scoreBreakdown"]
    assert abs(b["scoreCheck"] - s["complianceScore"]) <= 0.2
    assert abs(b["pointsLost"] + s["complianceScore"] - 100) <= 0.1
    assert sum(v["count"] for v in b["byStatus"].values()) == s["counts"]["inScope"]
    assert b["topLosses"] and b["topLosses"] == sorted(b["topLosses"], key=lambda x: -x["pointsLost"])
    assert "credit" in b["formula"] and 0 <= b["plainCompliantShare"] <= 100


def test_breakdown_unit_cases():
    a = [{"obligationId": "x1", "regCode": "R", "clause": "1", "status": "compliant", "severity": 3.0, "text": "a"},
         {"obligationId": "x2", "regCode": "R", "clause": "2", "status": "partial", "severity": 3.0, "text": "b"},
         {"obligationId": "x3", "regCode": "R", "clause": "3", "status": "uncovered", "severity": 4.0, "text": "c"}]
    b = score_breakdown(a, 55.0)  # (3 + 1.5 + 0) / 10 = 45%  -> check recomputes independently of the passed score
    assert b["scoreCheck"] == 45.0 and b["byStatus"]["partial"]["points"] == 15.0
    assert b["topLosses"][0]["obligationId"] == "x3" and b["topLosses"][0]["pointsLost"] == 40.0


def test_breakdown_empty_state_is_safe():
    b = score_breakdown([], 0.0)
    assert b["scoreCheck"] == 0.0 and b["topLosses"] == [] and b["plainCompliantShare"] == 0.0
