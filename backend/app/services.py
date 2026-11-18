"""Glue between the database and the pure engine."""
from __future__ import annotations

import csv
import io
import os
import zipfile
from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import db as m
from .engine import loaders
from .engine.model import PO, Contract, ContractLine, Dataset, Item, PRLine, Supplier
from .engine.pipeline import OUTPUT_COLUMNS, BatchResult, Engine, PolicyBook
from .ingest.contract_pdf import extract_contract_pdf
from .policy import service as pol

_cache: dict = {"stamp": None, "ds": None}


def bump_cache() -> None:
    _cache["stamp"] = None


# ---------------------------------------------------------------- ingest
def _text(b: bytes) -> str:
    return b.decode("utf-8-sig", errors="replace")


def ingest_files(db: Session, files: dict[str, bytes], actor: str) -> dict:
    """Load any subset of kit files. Recognised by file name; a .zip is unpacked."""
    flat: dict[str, bytes] = {}
    for name, data in files.items():
        if name.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for zi in z.infolist():
                    if not zi.is_dir() and not os.path.basename(zi.filename).startswith("."):
                        flat[zi.filename] = z.read(zi)
        else:
            flat[name] = data
    by_base = {}
    pdfs = []
    for name, data in flat.items():
        base = os.path.basename(name).lower()
        if base.endswith(".pdf") and base.startswith("rc-"):
            pdfs.append((name, data))
        elif base.endswith(".csv"):
            by_base[base] = data
    loaded: dict[str, int] = {}
    if "item_master.csv" in by_base:
        db.execute(delete(m.Item))
        items = loaders.items_from_csv(_text(by_base["item_master.csv"]))
        for it in items.values():
            db.add(m.Item(**it.__dict__))
        loaded["items"] = len(items)
    if "supplier_master.csv" in by_base:
        db.execute(delete(m.Supplier))
        sups = loaders.suppliers_from_csv(_text(by_base["supplier_master.csv"]))
        for s in sups.values():
            db.add(m.Supplier(supplier_id=s.supplier_id, name=s.name, city=s.city, categories=";".join(s.categories),
                              status=s.status, on_time_pct=s.on_time_pct, quality_rating=s.quality_rating))
        loaded["suppliers"] = len(sups)
    if "plants.csv" in by_base:
        db.execute(delete(m.Plant))
        pl = loaders.plants_from_csv(_text(by_base["plants.csv"]))
        for k, v in pl.items():
            db.add(m.Plant(code=k, name=v))
        loaded["plants"] = len(pl)
    if "po_history.csv" in by_base:
        db.execute(delete(m.PoHistory))
        pos = loaders.pos_from_csv(_text(by_base["po_history.csv"]))
        db.add_all([m.PoHistory(**p.__dict__) for p in pos])
        loaded["po_history"] = len(pos)
    if "contract_register.csv" in by_base and "contract_lines.csv" in by_base:
        db.execute(delete(m.ContractLine))
        db.execute(delete(m.Contract).where(m.Contract.source == "register"))
        db.flush()
        cons = loaders.contracts_from_csv(_text(by_base["contract_register.csv"]), _text(by_base["contract_lines.csv"]))
        existing = {c for (c,) in db.execute(select(m.Contract.contract_id))}
        for c in cons.values():
            if c.contract_id in existing:
                db.execute(delete(m.Contract).where(m.Contract.contract_id == c.contract_id))
                db.flush()
            db.add(_contract_row(c, "register", actor))
        loaded["contracts_register"] = len(cons)
    db.flush()
    added_pdf, skipped_pdf = [], []
    for name, data in sorted(pdfs):
        try:
            c = extract_contract_pdf(data)
        except Exception as e:  # noqa: BLE001
            skipped_pdf.append(f"{os.path.basename(name)}: unreadable ({e})")
            continue
        if not c.get("contract_id") or c["warnings"]:
            skipped_pdf.append(f"{os.path.basename(name)}: {'; '.join(c['warnings']) or 'no contract id'}")
            continue
        if db.get(m.Contract, c["contract_id"]):
            skipped_pdf.append(f"{c['contract_id']}: already in the register")
            continue
        save_contract(db, c, actor, source="pdf")
        added_pdf.append(c["contract_id"])
    if added_pdf:
        loaded["contracts_from_pdf"] = len(added_pdf)
    m.audit(db, actor, "data.load", "dataset", "kit", {"loaded": loaded, "pdf_added": added_pdf, "pdf_skipped": skipped_pdf})
    db.commit()
    bump_cache()
    return {"loaded": loaded, "pdf_contracts_added": added_pdf, "pdf_skipped": skipped_pdf}


def ingest_dir(db: Session, path: str, actor: str = "system") -> dict:
    files = {}
    for root, _, names in os.walk(path):
        for n in names:
            if n.lower().endswith((".csv", ".pdf")) and "pr_batch" not in root:
                with open(os.path.join(root, n), "rb") as f:
                    files[os.path.join(root, n)] = f.read()
    return ingest_files(db, files, actor)


def _contract_row(c: Contract, source: str, actor: str) -> m.Contract:
    row = m.Contract(contract_id=c.contract_id, supplier_id=c.supplier_id, supplier_name=c.supplier_name, start_date=c.start_date,
                     end_date=c.end_date, value_cap=c.value_cap, consumed_value=c.consumed_value, source=source, created_by=actor)
    row.lines = [m.ContractLine(item_code=l.item_code, description=l.description, uom=l.uom, rate=l.rate) for l in c.lines.values()]
    return row


def save_contract(db: Session, c: dict, actor: str, source: str = "manual") -> m.Contract:
    from .engine.loaders import parse_date

    sd = c["start_date"] if isinstance(c["start_date"], date) else parse_date(str(c["start_date"]))
    ed = c["end_date"] if isinstance(c["end_date"], date) else parse_date(str(c["end_date"]))
    if not (c.get("contract_id") and c.get("supplier_id") and sd and ed and c.get("value_cap")):
        raise ValueError("Contract id, supplier, start date, end date and value ceiling are required.")
    if ed < sd:
        raise ValueError("End date is before start date.")
    if not c.get("lines"):
        raise ValueError("Add at least one item line.")
    sup = db.get(m.Supplier, c["supplier_id"])
    if sup is None:
        raise ValueError(f"Supplier {c['supplier_id']} is not in the supplier master.")
    for l in c["lines"]:
        if not db.get(m.Item, l["item_code"]):
            raise ValueError(f"Item {l['item_code']} is not in the item master.")
        if float(l["rate"]) <= 0:
            raise ValueError(f"Rate for {l['item_code']} must be positive.")
    old = db.get(m.Contract, c["contract_id"])
    if old is not None:
        db.delete(old)
        db.flush()
    row = m.Contract(contract_id=c["contract_id"], supplier_id=c["supplier_id"], supplier_name=c.get("supplier_name") or sup.name,
                     start_date=sd, end_date=ed, value_cap=float(c["value_cap"]), consumed_value=float(c.get("consumed_value") or 0),
                     source=source, created_by=actor)
    row.lines = [m.ContractLine(item_code=l["item_code"], description=l.get("description") or db.get(m.Item, l["item_code"]).description,
                                uom=l.get("uom") or db.get(m.Item, l["item_code"]).uom, rate=float(l["rate"])) for l in c["lines"]]
    db.add(row)
    m.audit(db, actor, "contract.save", "contract", c["contract_id"], {"source": source, "lines": len(c["lines"]), "replaced": old is not None})
    bump_cache()
    return row


# ---------------------------------------------------------------- dataset
def _stamp(db: Session):
    return (
        db.scalar(select(func.count()).select_from(m.Item)), db.scalar(select(func.count()).select_from(m.Supplier)),
        db.scalar(select(func.count()).select_from(m.PoHistory)), db.scalar(select(func.max(m.Audit.id)).where(m.Audit.action.in_(["data.load", "contract.save", "contract.delete"]))),
    )


def dataset(db: Session) -> Dataset:
    st = _stamp(db)
    if _cache["ds"] is not None and _cache["stamp"] == st:
        return _cache["ds"]
    items = {r.item_code: Item(r.item_code, r.description, r.uom, r.category, r.item_type, r.standard_price) for r in db.scalars(select(m.Item))}
    sups = {r.supplier_id: Supplier(r.supplier_id, r.name, r.city, tuple(c for c in r.categories.split(";") if c), r.status, r.on_time_pct, r.quality_rating)
            for r in db.scalars(select(m.Supplier))}
    plants = {r.code: r.name for r in db.scalars(select(m.Plant))}
    pos = [PO(r.po_number, r.po_date, r.supplier_id, r.item_code, r.quantity, r.uom, r.unit_price, r.plant, r.delivered_on_time) for r in db.scalars(select(m.PoHistory))]
    cons = {}
    for r in db.scalars(select(m.Contract)):
        cons[r.contract_id] = Contract(r.contract_id, r.supplier_id, r.supplier_name, r.start_date, r.end_date, r.value_cap, r.consumed_value,
                                       {l.item_code: ContractLine(l.item_code, l.rate, l.description, l.uom) for l in r.lines}, r.source)
    ds = Dataset(items, sups, plants, pos, cons)
    _cache.update(ds=ds, stamp=st)
    return ds


def data_ready(db: Session) -> bool:
    return bool(db.scalar(select(func.count()).select_from(m.Item))) and bool(db.scalar(select(func.count()).select_from(m.Supplier)))


# ---------------------------------------------------------------- policies
def ensure_default_policy(db: Session) -> None:
    if db.scalar(select(func.count()).select_from(m.PolicyVersion)):
        return
    doc = pol.load_default()
    db.add(m.PolicyVersion(version=doc["version"], effective_from=date.fromisoformat(doc["effective_from"]), status="approved", document=doc,
                           changes=[{"kind": "meta", "text": "Initial policy loaded from Corvo Procurement Policy v5.0."}],
                           source_name="Corvo_Procurement_Policy.pdf (v5.0)", created_by="system", decided_by="system", decided_at=m.now()))
    m.audit(db, "system", "policy.seed", "policy", doc["version"])
    db.commit()


def approved_versions(db: Session) -> list[m.PolicyVersion]:
    return list(db.scalars(select(m.PolicyVersion).where(m.PolicyVersion.status == "approved").order_by(m.PolicyVersion.decided_at, m.PolicyVersion.id)))


def policy_book(db: Session, mode: str = "by_date", extra: m.PolicyVersion | None = None) -> PolicyBook:
    refs = [pol.to_ref(v) for v in approved_versions(db)]
    if extra is not None:
        refs.append(pol.to_ref(extra))
    return PolicyBook(refs, mode)


def active_policy(db: Session, on: date | None = None) -> m.PolicyVersion:
    vs = approved_versions(db)
    on = on or date.today()
    cur = vs[0]
    for v in sorted(vs, key=lambda v: v.effective_from):
        if v.effective_from <= on:
            cur = v
    return cur


def latest_policy(db: Session) -> m.PolicyVersion:
    vs = approved_versions(db)
    return sorted(vs, key=lambda v: v.effective_from)[-1]


# ---------------------------------------------------------------- runs
def run_engine(db: Session, lines: list[PRLine], mode: str = "by_date", extra: m.PolicyVersion | None = None) -> BatchResult:
    return Engine(dataset(db), policy_book(db, mode, extra)).run(lines)


def save_run(db: Session, result: BatchResult, name: str, source: str, mode: str, actor: str, input_csv: str = "") -> m.Run:
    run = m.Run(name=name, source=source, mode=mode, created_by=actor, policy_versions=result.summary.get("policy_versions", []),
                summary=result.summary, rows=result.rows, requirements=[r.as_dict() for r in result.requirements],
                purchase_orders=result.purchase_orders, input_csv=input_csv)
    db.add(run)
    db.flush()
    m.audit(db, actor, "run.process", "run", run.id, {"name": name, "lines": result.summary["lines"], "mode": mode,
                                                     "policy_versions": result.summary.get("policy_versions")})
    db.commit()
    return run


def rows_to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def inbox_lines(db: Session) -> list[m.PRInbox]:
    return list(db.scalars(select(m.PRInbox).where(m.PRInbox.status == "open").order_by(m.PRInbox.created_at)))


def inbox_to_prlines(rows: list[m.PRInbox]) -> list[PRLine]:
    return [PRLine(r.pr_no, r.pr_line, r.created_at, r.requester, r.department, r.plant, r.item_code, r.description, r.quantity, r.uom,
                   r.estimated_unit_price, r.need_by_date, r.urgency) for r in rows]
