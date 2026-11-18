"""Policy as data: versions, AI-read amendments, manual edits, impact preview, approval."""
from __future__ import annotations

import copy
from datetime import date

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import select

from .. import db as m
from .. import services as svc
from ..ai import client as ai
from ..ai.policy_reader import read_amendment
from ..engine.loaders import pr_lines_from_csv
from ..engine.rules import FACTS, OPS, describe
from ..ingest.contract_pdf import pdf_text
from ..policy import service as pol
from .deps import current_user, get_db, require

router = APIRouter(prefix="/api/policies")


def _out(v: m.PolicyVersion, full: bool = True) -> dict:
    d = {"id": v.id, "version": v.version, "effective_from": v.effective_from.isoformat(), "status": v.status,
         "base_version": v.base_version, "changes": v.changes, "warnings": v.warnings, "ai_notes": v.ai_notes,
         "source_name": v.source_name, "created_by": v.created_by, "created_at": v.created_at.isoformat(timespec="seconds") + "Z",
         "decided_by": v.decided_by, "decided_at": v.decided_at.isoformat(timespec="seconds") + "Z" if v.decided_at else None,
         "decision_comment": v.decision_comment, "title": v.document.get("title"), "rule_count": len(v.document.get("rules", []))}
    if full:
        d["document"] = v.document
        d["rules_text"] = [{"id": r.get("id"), "name": r.get("name"), "when": describe(r.get("when")),
                            "then": pol.outcome_text(r.get("then") or {}), "enabled": r.get("enabled", True)} for r in v.document.get("rules", [])]
        d["source_text"] = v.source_text[:20000]
    return d


@router.get("")
def list_versions(db=Depends(get_db)):
    vs = list(db.scalars(select(m.PolicyVersion).order_by(m.PolicyVersion.id.desc())))
    today = date.today()
    active = svc.active_policy(db, today).id if any(v.status == "approved" for v in vs) else None
    latest = svc.latest_policy(db).id if active else None
    out = []
    for v in vs:
        d = _out(v, full=False)
        d["in_force_today"] = v.id == active
        d["latest_approved"] = v.id == latest
        out.append(d)
    return out


@router.get("/schema")
def schema():
    return {"facts": FACTS, "ops": OPS, "decisions": sorted(pol.DECISIONS), "supplier_modes": sorted(pol.SUPPLIER_MODES),
            "routes": pol.KNOWN_ROUTES, "params": {k: v[0] for k, v in pol.PARAM_LABELS.items()}}


@router.get("/{pid}")
def get_version(pid: int, db=Depends(get_db)):
    v = db.get(m.PolicyVersion, pid)
    require(v is not None, "Policy version not found", 404)
    return _out(v)


def _base(db, base_id: int | None) -> m.PolicyVersion:
    if base_id:
        b = db.get(m.PolicyVersion, base_id)
        require(b is not None and b.status == "approved", "Base version must be an approved version.")
        return b
    return svc.latest_policy(db)


def _make_draft(db, base: m.PolicyVersion, doc: dict, user: str, source_name: str, source_text: str, ai_notes: str,
                extra_warnings: list[str]) -> m.PolicyVersion:
    if doc.get("version") in (None, "", base.version):
        doc["version"] = pol.bump_version(base.version)
    existing = {v for (v,) in db.execute(select(m.PolicyVersion.version).where(m.PolicyVersion.status != "rejected"))}
    while doc["version"] in existing:
        doc["version"] = pol.bump_version(doc["version"])
    if not doc.get("effective_from"):
        doc["effective_from"] = date.today().isoformat()
        extra_warnings.append("The document states no effective date; it defaults to today. Change it before approving if needed.")
    errors = pol.validate(doc)
    try:
        eff = date.fromisoformat(str(doc["effective_from"]))
    except ValueError:
        eff = date.today()
    if eff < base.effective_from:
        extra_warnings.append(f"Effective date {eff} is before the base version's ({base.effective_from}).")
    v = m.PolicyVersion(version=doc["version"], effective_from=eff, status="draft", document=doc, base_version=base.version,
                        changes=pol.diff(base.document, doc), warnings=[*(f"Error: {e}" for e in errors), *extra_warnings],
                        ai_notes=ai_notes, source_name=source_name, source_text=source_text, created_by=user)
    db.add(v)
    db.flush()
    m.audit(db, user, "policy.draft", "policy", v.id, {"version": v.version, "base": base.version, "changes": len(v.changes), "source": source_name})
    db.commit()
    return v


@router.post("/draft/ai")
async def draft_from_amendment(file: UploadFile | None = File(default=None), text: str | None = Form(default=None),
                               base_id: int | None = Form(default=None), db=Depends(get_db), user=Depends(current_user)):
    """Upload an amendment (PDF/TXT/MD) or describe a change in words; the AI proposes edits on the latest version."""
    require(file is not None or (text and text.strip()), "Upload an amendment document or describe the change.")
    require(ai.available(), "The AI reader is not configured on this server (ANTHROPIC_API_KEY). Use 'Edit as JSON' to make the change by hand.", 503)
    base = _base(db, base_id)
    pdf_bytes, doc_text, name = None, None, "chat request"
    if file is not None:
        data = await file.read()
        name = file.filename or "amendment"
        if name.lower().endswith(".pdf"):
            pdf_bytes = data
            try:
                doc_text = pdf_text(data)
            except Exception:  # noqa: BLE001
                doc_text = ""
        else:
            doc_text = data.decode("utf-8", errors="replace")
    if text and text.strip():
        doc_text = (doc_text + "\n\nAdditional instruction from the user:\n" + text) if doc_text else text
    try:
        out = read_amendment(base.document, text=doc_text if not pdf_bytes else (text or None), pdf_bytes=pdf_bytes, source_name=name)
    except ai.AIError as e:
        require(False, str(e), 502)
    ops = out["operations"]
    if out.get("version") or out.get("effective_from") or out.get("title"):
        ops = [{"op": "set_meta", "version": out.get("version"), "effective_from": out.get("effective_from"), "title": out.get("title")}] + ops
    doc, problems = pol.apply_operations(base.document, ops)
    notes = out.get("summary", "")
    warnings = [*problems, *(f"Check: {u}" for u in out.get("uncertainties", []))]
    v = _make_draft(db, base, doc, user["name"], name, doc_text or "", notes, warnings)
    res = _out(v)
    res["operations"] = out["operations"]
    return res


@router.post("/draft/manual")
def draft_manual(body: dict, db=Depends(get_db), user=Depends(current_user)):
    base = _base(db, body.get("base_id"))
    doc = body.get("document")
    if doc is None and body.get("operations"):
        doc, problems = pol.apply_operations(base.document, body["operations"])
    else:
        problems = []
    require(isinstance(doc, dict), "Send the full policy document or a list of operations.")
    v = _make_draft(db, base, copy.deepcopy(doc), user["name"], body.get("source_name") or "manual edit", body.get("note", ""), body.get("note", ""), problems)
    return _out(v)


@router.put("/{pid}")
def update_draft(pid: int, body: dict, db=Depends(get_db), user=Depends(current_user)):
    v = db.get(m.PolicyVersion, pid)
    require(v is not None, "Policy version not found", 404)
    require(v.status == "draft", "Only drafts can be edited; approved versions are immutable.")
    doc = body.get("document")
    require(isinstance(doc, dict), "document is required")
    base = db.scalar(select(m.PolicyVersion).where(m.PolicyVersion.version == v.base_version, m.PolicyVersion.status == "approved"))
    errors = pol.validate(doc)
    v.document = doc
    v.version = str(doc.get("version") or v.version)
    try:
        v.effective_from = date.fromisoformat(str(doc.get("effective_from")))
    except ValueError:
        pass
    v.changes = pol.diff(base.document if base else {}, doc)
    v.warnings = [*(f"Error: {e}" for e in errors), *[w for w in (v.warnings or []) if not w.startswith("Error:")]]
    m.audit(db, user["name"], "policy.edit", "policy", v.id, {"version": v.version})
    db.commit()
    return _out(v)


@router.post("/{pid}/impact")
def impact(pid: int, body: dict | None = None, db=Depends(get_db)):
    """Re-run a recent batch with the draft treated as approved, and list the decisions that would change."""
    v = db.get(m.PolicyVersion, pid)
    require(v is not None, "Policy version not found", 404)
    run_id = (body or {}).get("run_id")
    run = db.get(m.Run, run_id) if run_id else (
        db.scalar(select(m.Run).where(m.Run.input_csv != "", m.Run.source.in_(["upload", "api"])).order_by(m.Run.id.desc()))
        or db.scalar(select(m.Run).where(m.Run.input_csv != "").order_by(m.Run.id.desc())))
    require(run is not None and run.input_csv, "Process a PR batch first; the impact preview replays the latest batch.")
    lines = pr_lines_from_csv(run.input_csv)
    mode = (body or {}).get("mode", "by_date")
    before = svc.run_engine(db, lines, mode).rows
    after = svc.run_engine(db, lines, mode, extra=v if v.status != "approved" else None).rows
    bmap = {(r["pr_no"], r["pr_line"]): r for r in before}
    changed = []
    for r in after:
        b = bmap[(r["pr_no"], r["pr_line"])]
        diffs = {k: [b[k], r[k]] for k in ("route", "supplier_id", "unit_price", "group_value_inr", "suggested_supplier_ids", "group_id") if str(b[k]) != str(r[k])}
        if diffs:
            changed.append({"pr_no": r["pr_no"], "pr_line": r["pr_line"], "item": r["resolved_item_code"], "changes": diffs,
                            "policy_before": b["policy_version"], "policy_after": r["policy_version"], "reason_after": r["reason"]})
    used_after = sorted({r["policy_version"] for r in after})
    note = None
    if v.version not in used_after:
        note = (f"No requirement in this batch falls on or after {v.effective_from}, so v{v.version} would not decide any line "
                "(decisions follow the version in force on each requirement date).")
    return {"run_id": run.id, "run_name": run.name, "lines": len(after), "changed": changed, "versions_used_after": used_after, "note": note,
            "routes_before": _count(r["route"] for r in before), "routes_after": _count(r["route"] for r in after)}


def _count(it):
    out = {}
    for x in it:
        out[x] = out.get(x, 0) + 1
    return out


@router.post("/{pid}/approve")
def approve(pid: int, body: dict | None = None, db=Depends(get_db), user=Depends(current_user)):
    v = db.get(m.PolicyVersion, pid)
    require(v is not None, "Policy version not found", 404)
    require(v.status == "draft", f"Version is already {v.status}.")
    errors = pol.validate(v.document)
    require(not errors, "Fix these before approving: " + "; ".join(errors))
    clash = db.scalar(select(m.PolicyVersion).where(m.PolicyVersion.version == v.version, m.PolicyVersion.status == "approved"))
    require(clash is None, f"Version {v.version} is already approved; give this draft a new version number.")
    v.status, v.decided_by, v.decided_at = "approved", user["name"], m.now()
    v.decision_comment = (body or {}).get("comment", "")
    m.audit(db, user["name"], "policy.approve", "policy", v.id, {"version": v.version, "effective_from": v.effective_from.isoformat()})
    db.commit()
    return _out(v)


@router.post("/{pid}/reject")
def reject(pid: int, body: dict | None = None, db=Depends(get_db), user=Depends(current_user)):
    v = db.get(m.PolicyVersion, pid)
    require(v is not None and v.status == "draft", "Only drafts can be rejected.")
    v.status, v.decided_by, v.decided_at = "rejected", user["name"], m.now()
    v.decision_comment = (body or {}).get("comment", "")
    m.audit(db, user["name"], "policy.reject", "policy", v.id, {"version": v.version})
    db.commit()
    return _out(v)
