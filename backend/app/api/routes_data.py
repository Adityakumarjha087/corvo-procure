"""Master data, contracts, preferred suppliers, setup and audit."""
from __future__ import annotations

import csv
import io
import os
from datetime import date

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select

from .. import db as m
from .. import services as svc
from ..ai import client as ai
from ..engine.matcher import ItemMatcher
from ..engine.suppliers import preferred_list, suggest
from ..ingest.contract_pdf import extract_contract_pdf
from .deps import current_user, get_db, require

router = APIRouter(prefix="/api")


@router.get("/health")
def health(db=Depends(get_db)):
    counts = {name: db.scalar(select(func.count()).select_from(t)) for name, t in
              [("items", m.Item), ("suppliers", m.Supplier), ("po_history", m.PoHistory), ("contracts", m.Contract),
               ("policy_versions", m.PolicyVersion), ("runs", m.Run), ("open_prs", m.PRInbox)]}
    pv = svc.active_policy(db) if counts["policy_versions"] else None
    return {"status": "ok", "database": m.DATABASE_URL.split(":")[0], "ai_available": ai.available(), "ai_model": ai.MODEL,
            "data_ready": svc.data_ready(db), "counts": counts,
            "active_policy": {"version": pv.version, "effective_from": pv.effective_from.isoformat()} if pv else None}


@router.post("/setup/upload")
async def upload_kit(files: list[UploadFile] = File(...), db=Depends(get_db), user=Depends(current_user)):
    payload = {f.filename: await f.read() for f in files}
    return svc.ingest_files(db, payload, user["name"])


@router.post("/setup/load-local")
def load_local(db=Depends(get_db), user=Depends(current_user)):
    kit = os.getenv("KIT_DIR", "")
    require(bool(kit) and os.path.isdir(kit), "KIT_DIR is not set on the server; upload the kit files instead.")
    return svc.ingest_dir(db, kit, user["name"])


@router.get("/items")
def items(q: str | None = None, db=Depends(get_db)):
    ds = svc.dataset(db)
    if q:
        cands = ItemMatcher(ds.items).score_all(q)[:8]
        return [{**ds.items[c.item_code].__dict__, "score": c.score} for c in cands if c.score >= 0.3]
    return [i.__dict__ for i in sorted(ds.items.values(), key=lambda i: i.item_code)]


@router.get("/suppliers")
def suppliers(db=Depends(get_db)):
    return [{"supplier_id": s.supplier_id, "name": s.name, "city": s.city, "categories": s.categories.split(";"), "status": s.status,
             "on_time_pct": s.on_time_pct, "quality_rating": s.quality_rating} for s in db.scalars(select(m.Supplier).order_by(m.Supplier.supplier_id))]


@router.get("/plants")
def plants(db=Depends(get_db)):
    return [{"code": p.code, "name": p.name} for p in db.scalars(select(m.Plant))]


# ---------------------------------------------------------------- contracts
@router.get("/contracts")
def contracts(on: date | None = None, db=Depends(get_db)):
    on = on or date.today()
    sups = {s.supplier_id: s for s in db.scalars(select(m.Supplier))}
    out = []
    for c in db.scalars(select(m.Contract).order_by(m.Contract.start_date)):
        s = sups.get(c.supplier_id)
        state = "expired" if c.end_date < on else "upcoming" if c.start_date > on else "active"
        out.append({"contract_id": c.contract_id, "supplier_id": c.supplier_id, "supplier_name": c.supplier_name or (s.name if s else ""),
                    "supplier_status": s.status if s else "Unknown", "start_date": c.start_date.isoformat(), "end_date": c.end_date.isoformat(),
                    "value_cap": c.value_cap, "consumed_value": c.consumed_value, "ceiling_left": c.value_cap - c.consumed_value,
                    "source": c.source, "state": state, "created_by": c.created_by,
                    "lines": [{"item_code": l.item_code, "description": l.description, "uom": l.uom, "rate": l.rate} for l in c.lines]})
    return out


@router.post("/contracts/extract")
async def extract_contract(file: UploadFile = File(...), db=Depends(get_db)):
    data = await file.read()
    require(file.filename.lower().endswith(".pdf"), "Upload the signed contract as a PDF.")
    try:
        c = extract_contract_pdf(data)
    except Exception as e:  # noqa: BLE001
        require(False, f"Could not read this PDF: {e}")
    for k in ("start_date", "end_date"):
        if c.get(k):
            c[k] = c[k].isoformat()
    sup = db.get(m.Supplier, c.get("supplier_id") or "")
    if sup:
        c["supplier_status"] = sup.status
        if sup.status != "Active":
            c["warnings"].append(f"Supplier {sup.supplier_id} is {sup.status}; the policy will not use this contract.")
    elif c.get("supplier_id"):
        c["warnings"].append(f"Supplier {c['supplier_id']} is not in the supplier master.")
    if c.get("contract_id") and db.get(m.Contract, c["contract_id"]):
        c["warnings"].append(f"{c['contract_id']} already exists; saving will replace it.")
    for l in c["lines"]:
        it = db.get(m.Item, l["item_code"])
        if not it:
            c["warnings"].append(f"{l['item_code']} is not in the item master.")
        elif it.uom != l["uom"]:
            c["warnings"].append(f"{l['item_code']} unit {l['uom']} differs from item master {it.uom}.")
    c["filename"] = file.filename
    return c


@router.post("/contracts")
def save_contract(body: dict, db=Depends(get_db), user=Depends(current_user)):
    try:
        row = svc.save_contract(db, body, user["name"], source=body.get("source") if body.get("source") in ("pdf", "manual") else "manual")
    except (ValueError, KeyError) as e:
        require(False, str(e))
    db.commit()
    return {"ok": True, "contract_id": row.contract_id}


@router.delete("/contracts/{cid}")
def delete_contract(cid: str, db=Depends(get_db), user=Depends(current_user)):
    c = db.get(m.Contract, cid)
    require(c is not None, "Contract not found", 404)
    require(c.source != "register", "Register contracts are reloaded from the register file and cannot be deleted here.")
    db.delete(c)
    m.audit(db, user["name"], "contract.delete", "contract", cid)
    db.commit()
    svc.bump_cache()
    return {"ok": True}


# ---------------------------------------------------------------- preferred suppliers
@router.get("/preferred")
def preferred(item_code: str, as_of: date | None = None, db=Depends(get_db)):
    ds = svc.dataset(db)
    require(item_code in ds.items, f"Unknown item {item_code}", 404)
    as_of = as_of or date.today()
    pv = svc.active_policy(db, as_of)
    ranked = preferred_list(ds, item_code, as_of, pv.document)
    it = ds.items[item_code]
    excluded = []
    seen = {r.supplier_id for r in ranked}
    lookback = pv.document.get("preferred_suppliers", {}).get("lookback_days", 548)
    for p in ds.pos_for_item(item_code, as_of, lookback):
        s = ds.suppliers.get(p.supplier_id)
        if p.supplier_id not in seen and s:
            excluded.append({"supplier_id": s.supplier_id, "name": s.name, "status": s.status, "reason": f"{s.status} supplier"})
            seen.add(p.supplier_id)
    for c in ds.contracts_for_item(item_code):
        s = ds.suppliers.get(c.supplier_id)
        if c.supplier_id not in seen and s:
            excluded.append({"supplier_id": s.supplier_id, "name": s.name, "status": s.status,
                             "reason": f"{s.status} supplier" if s.status != "Active" else f"contract {c.contract_id} starts {c.start_date}"})
            seen.add(c.supplier_id)
    return {"item": it.__dict__, "as_of": as_of.isoformat(), "policy_version": pv.version,
            "weights": pv.document.get("preferred_suppliers", {}).get("weights"),
            "ranked": [r.as_dict() for r in ranked], "excluded": excluded,
            "suggestions_5": suggest(ds, item_code, it.category, ranked, 5, pv.document)}


def _preferred_rows(db, as_of: date, top: int):
    ds = svc.dataset(db)
    pv = svc.active_policy(db, as_of)
    rows = []
    for code in sorted(ds.items):
        for r in preferred_list(ds, code, as_of, pv.document)[:top]:
            rows.append({"item_code": code, "rank": r.rank, "supplier_id": r.supplier_id,
                         "reference_price": round(r.reference_price, 2) if r.reference_price is not None else ""})
    return rows, pv


@router.get("/preferred/all")
def preferred_all(as_of: date | None = None, top: int = 3, db=Depends(get_db)):
    as_of = as_of or date.today()
    rows, pv = _preferred_rows(db, as_of, top)
    return {"as_of": as_of.isoformat(), "policy_version": pv.version, "rows": rows}


@router.get("/preferred/export.csv", response_class=PlainTextResponse)
def preferred_export(as_of: date = Query(...), top: int = 3, db=Depends(get_db), user=Depends(current_user)):
    rows, pv = _preferred_rows(db, as_of, top)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["item_code", "rank", "supplier_id", "reference_price"], lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    m.audit(db, user["name"], "preferred.export", "preferred", as_of.isoformat(), {"rows": len(rows), "policy_version": pv.version})
    db.commit()
    return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="preferred_{as_of.isoformat()}.csv"'})


@router.get("/audit")
def audit_log(limit: int = 200, entity: str | None = None, db=Depends(get_db)):
    q = select(m.Audit).order_by(m.Audit.id.desc()).limit(min(limit, 1000))
    if entity:
        q = q.where(m.Audit.entity == entity)
    return [{"id": a.id, "at": a.at.isoformat(timespec="seconds") + "Z", "actor": a.actor, "action": a.action, "entity": a.entity,
             "entity_id": a.entity_id, "detail": a.detail} for a in db.scalars(q)]
