import time

from fastapi.testclient import TestClient


def _client():
    from specforge.api.app import app
    return TestClient(app)


def _wait(c, jid):
    for _ in range(100):
        j = c.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("done", "error"):
            return j
        time.sleep(0.1)
    raise TimeoutError


def test_qc_flow_and_feedback():
    c = _client()
    jid = c.post("/api/qc/demo", data={"standard": "SDTM"}).json()["job_id"]
    j = _wait(c, jid)
    assert j["status"] == "done" and j["result"]["summary"]["total"] > 0
    f = j["result"]["findings"][0]
    assert c.post(f"/api/qc/{jid}/findings/{f['id']}", json={"decision": "dismissed"}).json()["ok"]
    r = c.get(f"/api/qc/{jid}/annotated.xlsx")
    assert r.status_code == 200 and r.content[:2] == b"PK"


def test_build_flow_zip():
    c = _client()
    jid = c.post("/api/build/demo", data={"standard": "ADaM"}).json()["job_id"]
    j = _wait(c, jid)
    assert j["status"] == "done"
    assert {d["dataset"] for d in j["result"]["datasets"]} == {"ADSL", "ADAE"}
    assert c.get(f"/api/build/{jid}/download.zip").content[:2] == b"PK"


def test_public_demo_blocks_uploads(monkeypatch):
    import specforge.api.app as appmod

    monkeypatch.setattr(appmod, "PUBLIC_DEMO", True)
    c = TestClient(appmod.app)
    assert c.get("/api/health").json()["offline"] is True
    r = c.post("/api/qc", data={"standard": "SDTM"}, files={"spec": ("s.csv", b"Variable\nAGE\n")})
    assert r.status_code == 403
