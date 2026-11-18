"""Chat intake endpoint."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from .. import db as m
from .. import services as svc
from ..ai.chat import ChatEngine
from ..engine.model import PRLine
from .deps import current_user, get_db, require

router = APIRouter(prefix="/api/chat")


def _engine(db) -> ChatEngine:
    ds = svc.dataset(db)
    return ChatEngine(ds.items, ds.plants)


def _preview(db, draft: dict, user: dict) -> dict | None:
    """Decide the draft together with the open PRs, the way a buyer would see it after processing."""
    try:
        open_lines = svc.inbox_to_prlines(svc.inbox_lines(db))
        line = PRLine("PREVIEW", 1, datetime.now().replace(second=0, microsecond=0), user["name"], "", draft["plant"],
                      "" if draft.get("is_new") else (draft.get("item_code") or ""), draft.get("item_description") or "",
                      float(draft["quantity"]), draft.get("uom") or "", draft.get("estimated_unit_price"),
                      date.fromisoformat(draft["need_by_date"]), draft.get("urgency") or "Normal")
        res = svc.run_engine(db, open_lines + [line])
        row = next(r for r in res.rows if r["pr_no"] == "PREVIEW")
        req = next((r for r in res.requirements if any(l.pr_no == "PREVIEW" for l in r.lines)), None)
        return {"route": row["route"], "decision": row["decision"], "supplier_id": row["supplier_id"], "unit_price": row["unit_price"],
                "value": row["group_value_inr"], "suggested": row["suggested_supplier_ids"], "reason": row["reason"],
                "policy_version": row["policy_version"], "clubbed_with": [f"{l['pr_no']}/{l['pr_line']}" for l in (req.as_dict()["lines"] if req else []) if l["pr_no"] != "PREVIEW"],
                "supplier_name": req.supplier_name if req else None}
    except Exception:  # noqa: BLE001  preview is best-effort
        return None


@router.post("")
def chat(body: dict, db=Depends(get_db), user=Depends(current_user)):
    require(svc.data_ready(db), "Master data is not loaded yet. Ask an admin to load the kit in Data setup.", 409)
    sid = body.get("session_id") or uuid.uuid4().hex
    sess = db.get(m.ChatSession, sid)
    if sess is None:
        sess = m.ChatSession(id=sid, user=user["name"], messages=[], state={})
        db.add(sess)
    ce = _engine(db)
    msg = (body.get("message") or "").strip()
    if not msg:
        reply, state = ce.start(), {}
    else:
        reply, state = ce.handle(msg, dict(sess.state or {}))
    created = None
    if reply.get("commit"):
        d = reply["draft"]
        n = (db.scalar(select(func.count()).select_from(m.PRInbox)) or 0) + 1
        pr = m.PRInbox(pr_no=f"PR-C-{n:05d}", pr_line=1, created_at=datetime.now().replace(microsecond=0), requester=user["name"],
                       department=body.get("department") or state.get("draft", {}).get("department") or "", plant=d["plant"],
                       item_code="" if d["is_new"] else d["item_code"], description=d["item_description"] or "", quantity=float(d["quantity"]),
                       uom=d.get("uom") or "", estimated_unit_price=d.get("estimated_unit_price"), need_by_date=date.fromisoformat(d["need_by_date"]),
                       urgency=d.get("urgency") or "Normal", chat_session_id=sid)
        db.add(pr)
        db.flush()
        m.audit(db, user["name"], "pr.create", "pr", pr.pr_no, {"via": "chat", "item": pr.item_code or "NEW", "qty": pr.quantity, "plant": pr.plant})
        created = {"pr_no": pr.pr_no, "item_code": pr.item_code or "NEW", "description": pr.description, "quantity": pr.quantity, "uom": pr.uom,
                   "plant": pr.plant, "need_by_date": pr.need_by_date.isoformat(), "urgency": pr.urgency}
        nxt, state = ce.next_from_queue(state)
        reply = nxt or {"text": f"Done — **{pr.pr_no}** is raised and waiting for Procurement. Anything else?"}
        if nxt:
            reply["text"] = f"Done — **{pr.pr_no}** is raised. " + reply["text"]
        reply["created"] = created
    if reply.get("ready") and reply.get("draft"):
        reply["preview"] = _preview(db, reply["draft"], user)
    sess.messages = [*(sess.messages or []), *([{"role": "user", "text": msg}] if msg else []),
                     {"role": "assistant", "text": reply.get("text", ""), "created": created}]
    sess.state = state
    sess.updated_at = m.now()
    db.commit()
    return {"session_id": sid, **reply}


@router.get("/{sid}")
def history(sid: str, db=Depends(get_db)):
    sess = db.get(m.ChatSession, sid)
    require(sess is not None, "Session not found", 404)
    return {"session_id": sid, "messages": sess.messages, "state": sess.state}
