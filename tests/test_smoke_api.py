from tests.conftest import ADMIN, ANALYST, VIEWER


async def test_sample_pipeline(client):
    r = await client.post("/api/v1/sample/load", headers={**ANALYST, "Idempotency-Key": "sample-load-0001"})
    assert r.status_code == 200, r.text
    print(r.json()["complianceScore"], r.json()["gaps"])
    s = (await client.get("/api/v1/analysis/summary", headers=VIEWER)).json()
    print(s)
    assert s["counts"]["gaps"] > 0
