"""Batch processing, buyer workspace actions (approve / override), exports, PR inbox."""
from __future__ import annotations

import copy

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select

from .. import db as m
from .. import services as svc
from ..engine.loaders import PR_COLUMNS, pr_lines_from_csv
from .deps import current_user, get_db, require

router = APIRouter(prefix="/api")


def _decisions(run: m.Run, actions: list[m.Action]) -> dict:
    """Effective state for every work item: a PO (po_id) or a sourcing requirement (group_id)."""
    state: dict = {}
    for a in sorted(actions, key=lambda a: a.id):
        s = state.setdefault(a.target, {"status": "pending", "history": []})
        s["history"].append({"kind": a.kind, "actor": a.actor, "at": a.at.isoformat(timespec="seconds") + "Z", "comment": a.comment, "payload": a.payload})
        if a.kind == "approve":
            s["status"], s["doc_no"] = "approved", a.payload.get("doc_no")
        elif a.kind == "override":
            s["status"] = "overridden" if s["status"] != "approved" else s["status"]
            s["override"] = a.payload
        elif a.kind == "reject":
            s["status"] = "rejected"
    return state


def _effective_rows(run: m.Run, state: dict) -> list[dict]:
    rows = copy.deepcopy(run.rows)
    for r in rows:
        ov = state.get(r["group_id"], {}).get("override")
        if ov:
            for k in ("decision", "route", "supplier_id", "unit_price", "suggested_supplier_ids"):
                if k in ov:
                    r[k] = ov[k]
            r["po_id"] = "" if ov.get("decision") != "PO" else (r["po_id"] or f"OVR-{r['group_id']}")
            r["reason"] = f"Buyer override by {ov.get('actor')}: {ov.get('comment')} | Engine: {r['reason']}"
    return rows


def _run_out(db, run: m.Run, full: bool = True) -> dict:
    d = {"id": run.id, "name": run.name, "source": run.source, "mode": run.mode, "created_by": run.created_by,
         "created_at": run.created_at.isoformat(timespec="seconds") + "Z", "policy_versions": run.policy_versions, "summary": run.summary}
    if full:
        actions = list(db.scalars(select(m.Action).where(m.Action.run_id == run.id)))
        state = _decisions(run, actions)
        d.update(requirements=run.requirements, purchase_orders=run.purchase_orders, rows=run.rows, state=state)
        d["progress"] = {"approved": sum(1 for s in state.values() if s["status"] == "approved"),
                         "work_items": len(run.purchase_orders) + sum(1 for r in run.requirements if r["decision"] != "PO")}
    return d


@router.post("/process-batch")
async def process_batch(request: Request, file: UploadFile | None = File(default=None), mode: str = Query("by_date", pattern="^(by_date|latest)$"),
                        name: str | None = None, db=Depends(get_db), user=Depends(current_user)):
    """Process a PR batch CSV (multipart field `file`, or the raw CSV as the request body) and return one decision per line."""
    require(svc.data_ready(db), "Master data is not loaded yet. Upload the kit files in Data setup first.", 409)
    if file is not None:
        text = (await file.read()).decode("utf-8-sig", errors="replace")
        fname = file.filename or "batch.csv"
    else:
        text = (await request.body()).decode("utf-8-sig", errors="replace")
        fname = "api-body.csv"
    require(text.strip() != "", "The CSV is empty.")
    header = text.splitlines()[0].lower()
    missing = [c for c in ("pr_no", "created_at", "plant", "description", "quantity", "need_by_date") if c not in header]
    require(not missing, f"The CSV is missing columns: {', '.join(missing)}. Expected: {', '.join(PR_COLUMNS)}.")
    lines = pr_lines_from_csv(text)
    require(len(lines) > 0, "No PR lines found in the CSV.")
    result = svc.run_engine(db, lines, mode)
    run = svc.save_run(db, result, name or fname, "upload" if file is not None else "api", mode, user["name"], text)
    return {"run_id": run.id, "summary": result.summary, "decisions": result.rows}


@router.get("/runs")
def runs(db=Depends(get_db)):
    return [_run_out(db, r, full=False) for r in db.scalars(select(m.Run).order_by(m.Run.id.desc()))]


@router.get("/runs/{rid}")
def run_detail(rid: int, db=Depends(get_db)):
    run = db.get(m.Run, rid)
    require(run is not None, "Run not found", 404)
    return _run_out(db, run)


@router.get("/runs/{rid}/export.csv", response_class=PlainTextResponse)
def export(rid: int, with_overrides: bool = False, db=Depends(get_db), user=Depends(current_user)):
    run = db.get(m.Run, rid)
    require(run is not None, "Run not found", 404)
    rows = run.rows
    if with_overrides:
        rows = _effective_rows(run, _decisions(run, list(db.scalars(select(m.Action).where(m.Action.run_id == rid)))))
    m.audit(db, user["name"], "run.export", "run", rid, {"with_overrides": with_overrides})
    db.commit()
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in run.name.rsplit(".", 1)[0])[:60]
    return PlainTextResponse(svc.rows_to_csv(rows), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="decisions_run{rid}_{safe}.csv"'})


@router.post("/runs/{rid}/reprocess")
def reprocess(rid: int, body: dict | None = None, db=Depends(get_db), user=Depends(current_user)):
    run = db.get(m.Run, rid)
    require(run is not None and run.input_csv, "This run has no stored input to reprocess.")
    mode = (body or {}).get("mode", run.mode)
    result = svc.run_engine(db, pr_lines_from_csv(run.input_csv), mode)
    new = svc.save_run(db, result, f"{run.name} (reprocessed)", run.source, mode, user["name"], run.input_csv)
    return {"run_id": new.id, "summary": result.summary}


def _next_doc_no(db, prefix: str) -> str:
    n = db.scalar(select(func.count()).select_from(m.Document).where(m.Document.doc_no.like(f"{prefix}-%"))) or 0
    return f"{prefix}-{26}{n + 1:05d}"


@router.post("/runs/{rid}/approve")
def approve(rid: int, body: dict, db=Depends(get_db), user=Depends(current_user)):
    run = db.get(m.Run, rid)
    require(run is not None, "Run not found", 404)
    target = body.get("target", "")
    state = _decisions(run, list(db.scalars(select(m.Action).where(m.Action.run_id == rid))))
    require(state.get(target, {}).get("status") != "approved", f"{target} is already approved.")
    po = next((p for p in run.purchase_orders if p["po_id"] == target), None)
    req = next((r for r in run.requirements if r["group_id"] == target), None)
    require(po is not None or req is not None, f"Unknown work item {target}")
    if po is not None:
        reqs = [r for r in run.requirements if r["group_id"] in po["group_ids"]]
        doc = m.Document(doc_no=_next_doc_no(db, "PO"), kind="PO", run_id=rid, target=target, route=po["route"], supplier_id=po["supplier_id"],
                         plant=po["plant"], value=po["value"], created_by=user["name"],
                         body={"lines": po["lines"], "requirements": [{"group_id": r["group_id"], "item_code": r["item_code"], "quantity": r["quantity"],
                                                                       "unit_price": r["unit_price"], "reason": r["reason"]} for r in reqs]})
    else:
        ov = state.get(target, {}).get("override") or {}
        route = ov.get("route", req["route"])
        kind = {"RFQ": "RFQ", "RFP": "RFP", "CAPEX_SOURCING": "CAPEX", "NEW_ITEM_SOURCING": "NEWITEM"}.get(route, "PO" if ov.get("decision") == "PO" else "SRC")
        doc = m.Document(doc_no=_next_doc_no(db, kind), kind=route, run_id=rid, target=target, route=route,
                         supplier_id=ov.get("supplier_id") or req.get("supplier_id"), plant=req["plant"], value=req["value"] or 0, created_by=user["name"],
                         body={"item_code": req["item_code"], "quantity": req["quantity"], "suggested": ov.get("suggested_supplier_ids") or [s["supplier_id"] for s in req["suggestions"]],
                               "lines": req["lines"], "reason": req["reason"], "override": ov or None})
    db.add(doc)
    db.add(m.Action(run_id=rid, target=target, kind="approve", payload={"doc_no": doc.doc_no}, comment=body.get("comment", ""), actor=user["name"]))
    m.audit(db, user["name"], "decision.approve", "run", rid, {"target": target, "doc_no": doc.doc_no})
    db.commit()
    return {"ok": True, "doc_no": doc.doc_no, "kind": doc.kind}


@router.post("/runs/{rid}/override")
def override(rid: int, body: dict, db=Depends(get_db), user=Depends(current_user)):
    run = db.get(m.Run, rid)
    require(run is not None, "Run not found", 404)
    gid = body.get("group_id", "")
    req = next((r for r in run.requirements if r["group_id"] == gid), None)
    require(req is not None, f"Unknown requirement {gid}")
    comment = (body.get("comment") or "").strip()
    require(len(comment) >= 5, "An override needs a written reason (policy 8.1).")
    route = body.get("route") or req["route"]
    decision = "PO" if route.endswith("_PO") else "SOURCING_REQUEST"
    payload = {"decision": decision, "route": route, "comment": comment, "actor": user["name"],
               "original": {"route": req["route"], "supplier_id": req["supplier_id"], "unit_price": req["unit_price"]}}
    if decision == "PO":
        sid = body.get("supplier_id")
        require(bool(sid), "Choose the supplier for the PO.")
        sup = db.get(m.Supplier, sid)
        require(sup is not None, f"Unknown supplier {sid}")
        require(sup.status == "Active", f"{sid} {sup.name} is {sup.status}; policy 5.7 forbids POs to it.")
        try:
            price = float(body.get("unit_price"))
        except (TypeError, ValueError):
            price = None
        require(price is not None and price > 0, "Enter the unit price.")
        payload.update(supplier_id=sid, unit_price=price)
    else:
        ids = [s.strip() for s in (body.get("suggested_supplier_ids") or "").replace(",", ";").split(";") if s.strip()]
        for sid in ids:
            sup = db.get(m.Supplier, sid)
            require(sup is not None and sup.status == "Active", f"{sid} is not an Active supplier (policy 5.7).")
        payload.update(supplier_id="", unit_price="", suggested_supplier_ids=";".join(ids))
    db.add(m.Action(run_id=rid, target=gid, kind="override", payload=payload, comment=comment, actor=user["name"]))
    m.audit(db, user["name"], "decision.override", "run", rid, {"group_id": gid, **payload})
    db.commit()
    return {"ok": True}


@router.get("/documents")
def documents(db=Depends(get_db)):
    return [{"doc_no": d.doc_no, "kind": d.kind, "run_id": d.run_id, "target": d.target, "route": d.route, "supplier_id": d.supplier_id,
             "plant": d.plant, "value": d.value, "created_by": d.created_by, "created_at": d.created_at.isoformat(timespec="seconds") + "Z", "body": d.body}
            for d in db.scalars(select(m.Document).order_by(m.Document.id.desc()))]


# ---------------------------------------------------------------- PR inbox (from chat)
@router.get("/inbox")
def inbox(db=Depends(get_db)):
    return [{"id": r.id, "pr_no": r.pr_no, "pr_line": r.pr_line, "created_at": r.created_at.isoformat(sep=" ", timespec="minutes"),
             "requester": r.requester, "department": r.department, "plant": r.plant, "item_code": r.item_code, "description": r.description,
             "quantity": r.quantity, "uom": r.uom, "estimated_unit_price": r.estimated_unit_price,
             "need_by_date": r.need_by_date.isoformat(), "urgency": r.urgency, "status": r.status, "run_id": r.run_id}
            for r in db.scalars(select(m.PRInbox).order_by(m.PRInbox.id.desc()).limit(500))]


@router.post("/inbox/process")
def process_inbox(db=Depends(get_db), user=Depends(current_user)):
    rows = svc.inbox_lines(db)
    require(rows, "There are no open PRs to process.")
    lines = svc.inbox_to_prlines(rows)
    import csv
    import io

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(PR_COLUMNS)
    for l in lines:
        w.writerow([l.pr_no, l.pr_line, l.created_at.strftime("%Y-%m-%d %H:%M"), l.requester, l.department, l.plant, l.item_code, l.description,
                    l.quantity, l.uom, "" if l.estimated_unit_price is None else l.estimated_unit_price, l.need_by_date.isoformat(), l.urgency])
    result = svc.run_engine(db, lines, "by_date")
    run = svc.save_run(db, result, f"Chat PRs ({len(lines)} lines)", "inbox", "by_date", user["name"], buf.getvalue())
    for r in rows:
        r.status, r.run_id = "processed", run.id
    db.commit()
    return {"run_id": run.id, "summary": result.summary}
