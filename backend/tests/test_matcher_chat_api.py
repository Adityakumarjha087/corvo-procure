import os
from datetime import date

import pytest

from .conftest import KIT_DIR, needs_kit

pytestmark = needs_kit


@pytest.mark.parametrize("text,code", [
    ("brg 6308 ZZ for maintenance", "ITM-1022"), ("hyd hose 1/2 inch 2 wire", "ITM-1035"), ('monitor 24"', "ITM-1057"),
    ("welding rod e6013 3.15mm", "ITM-1015"), ("pneu cylinder 50x100", "ITM-1036"), ("hex nut m10 gr 8", "ITM-1010"),
    ("Forklift electric 2 ton - urgent", "ITM-1073"), ("hydraulic pump seal kit (hydrax) (repeat)", "ITM-1040"),
])
def test_matcher_short_forms(ds, text, code):
    from app.engine.matcher import ItemMatcher

    assert ItemMatcher(ds.items).match(None, text)["item_code"] == code


@pytest.mark.parametrize("text", ["Drinking water purifier 50 LPH", "Ultrasonic thickness gauge", "office chair"])
def test_matcher_never_invents(ds, text):
    from app.engine.matcher import ItemMatcher

    assert ItemMatcher(ds.items).match(None, text)["item_code"] is None


def test_chat_flow(ds):
    from app.ai.chat import ChatEngine

    ce = ChatEngine(ds.items, ds.plants, date(2026, 11, 16))
    r, st = ce.handle("need 200 nitrile gloves for Chakan by next Friday", {})
    assert r["draft"]["item_code"] == "ITM-1048" and r["draft"]["plant"] == "CHK1" and r["draft"]["need_by_date"] == "2026-11-20"
    assert st["awaiting"] == "urgency"
    r, st = ce.handle("normal", st)
    assert r.get("ready")
    r, st = ce.handle("yes", st)
    assert r.get("commit")


def test_chat_asks_on_ambiguous_and_unknown(ds):
    from app.ai.chat import ChatEngine

    ce = ChatEngine(ds.items, ds.plants, date(2026, 11, 16))
    r, st = ce.handle("ball bearing", {})
    assert st["awaiting"] == "item_choice" and len(r["candidates"]) >= 2
    r, st = ce.handle("ultrasonic thickness gauge 1 nos for PUN1", {})
    assert st["awaiting"] == "new_item_confirm" and r["draft"]["item_code"] is None


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path_factory.mktemp('db') / 'test.db'}"
    os.environ["KIT_DIR"] = KIT_DIR
    os.environ["AI_DISABLED"] = "1"
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def test_api_end_to_end(client):
    h = {"X-User": "pytest"}
    assert client.get("/api/health").json()["data_ready"]
    with open(os.path.join(KIT_DIR, "pr_batches", "sample_pr_batch.csv"), "rb") as f:
        res = client.post("/api/process-batch", files={"file": ("batch.csv", f, "text/csv")}, headers=h).json()
    assert len(res["decisions"]) == 186
    rid = res["run_id"]
    csv_text = client.get(f"/api/runs/{rid}/export.csv").text
    assert csv_text.splitlines()[0] == "pr_no,pr_line,resolved_item_code,group_id,po_id,decision,route,supplier_id,unit_price,group_value_inr,suggested_supplier_ids,policy_version,reason"
    run = client.get(f"/api/runs/{rid}").json()
    po = run["purchase_orders"][0]["po_id"]
    assert client.post(f"/api/runs/{rid}/approve", json={"target": po}, headers=h).json()["ok"]
    assert client.post(f"/api/runs/{rid}/approve", json={"target": po}, headers=h).status_code == 400  # twice
    req = next(r for r in run["requirements"] if r["decision"] == "SOURCING_REQUEST" and r["route"] == "RFQ")
    assert client.post(f"/api/runs/{rid}/override", json={"group_id": req["group_id"], "route": "SPOT_PO", "supplier_id": "S008", "unit_price": 1, "comment": "quote received"}, headers=h).status_code == 400
    assert client.post(f"/api/runs/{rid}/override", json={"group_id": req["group_id"], "route": "RFQ"}, headers=h).status_code == 400
    pref = client.get("/api/preferred/export.csv", params={"as_of": "2026-11-01"}).text.splitlines()
    assert pref[0] == "item_code,rank,supplier_id,reference_price" and any(l.startswith("ITM-1048,1,S029,") for l in pref)
    audit = client.get("/api/audit").json()
    assert any(a["action"] == "decision.approve" and a["actor"] == "pytest" for a in audit)


def test_api_policy_draft_and_approve(client):
    h = {"X-User": "pytest"}
    d = client.post("/api/policies/draft/manual", headers=h, json={"operations": [
        {"op": "set_meta", "version": "5.1", "effective_from": "2026-11-10"},
        {"op": "set_param", "path": "consolidation.window_hours", "value": 48}]}).json()
    assert any("48 hours" in c["text"] for c in d["changes"])
    imp = client.post(f"/api/policies/{d['id']}/impact", json={}).json()
    assert "changed" in imp
    ok = client.post(f"/api/policies/{d['id']}/approve", headers=h, json={"comment": "test"}).json()
    assert ok["status"] == "approved"
    assert client.post(f"/api/policies/{d['id']}/approve", headers=h, json={}).status_code == 400
