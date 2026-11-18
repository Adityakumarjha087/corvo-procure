"""Parse kit-format CSV text into engine types. Used by DB ingest, batch upload and tests."""
from __future__ import annotations

import csv
import io
import os
from datetime import date, datetime

from .model import PO, Contract, ContractLine, Dataset, Item, PRLine, Supplier


def _rows(text: str) -> list[dict[str, str]]:
    text = text.lstrip("﻿")
    return [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(io.StringIO(text))]


def _f(v: str | None) -> float | None:
    if v is None or str(v).strip() == "":
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def parse_date(v: str | None) -> date | None:
    if not v:
        return None
    v = v.strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%b-%Y", "%d %b %Y"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


def parse_datetime(v: str | None) -> datetime | None:
    if not v:
        return None
    v = v.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            continue
    d = parse_date(v)
    return datetime(d.year, d.month, d.day) if d else None


def items_from_csv(text: str) -> dict[str, Item]:
    out = {}
    for r in _rows(text):
        out[r["item_code"]] = Item(r["item_code"], r["description"], r["uom"], r["category"], r["item_type"], _f(r["standard_price"]) or 0.0)
    return out


def suppliers_from_csv(text: str) -> dict[str, Supplier]:
    out = {}
    for r in _rows(text):
        cats = tuple(c.strip() for c in r.get("categories", "").split(";") if c.strip())
        out[r["supplier_id"]] = Supplier(
            r["supplier_id"], r["name"], r.get("city", ""), cats, r.get("status", "Active"),
            _f(r.get("on_time_pct")) or 0.0, _f(r.get("quality_rating")) or 0.0,
        )
    return out


def plants_from_csv(text: str) -> dict[str, str]:
    return {r["plant"]: r.get("name", "") for r in _rows(text)}


def pos_from_csv(text: str) -> list[PO]:
    out = []
    for r in _rows(text):
        out.append(PO(
            r["po_number"], parse_date(r["po_date"]), r["supplier_id"], r["item_code"], _f(r["quantity"]) or 0.0,
            r.get("uom", ""), _f(r["unit_price"]) or 0.0, r.get("plant", ""),
            r.get("delivered_on_time", "").lower() in ("true", "1", "yes", "y"),
        ))
    return out


def contracts_from_csv(register_text: str, lines_text: str) -> dict[str, Contract]:
    out: dict[str, Contract] = {}
    for r in _rows(register_text):
        out[r["contract_id"]] = Contract(
            r["contract_id"], r["supplier_id"], r.get("supplier_name", ""), parse_date(r["start_date"]),
            parse_date(r["end_date"]), _f(r["value_cap"]) or 0.0, _f(r.get("consumed_value")) or 0.0, {}, "register",
        )
    for r in _rows(lines_text):
        c = out.get(r["contract_id"])
        if c:
            c.lines[r["item_code"]] = ContractLine(r["item_code"], _f(r["rate"]) or 0.0, r.get("description", ""), r.get("uom", ""))
    return out


PR_COLUMNS = ["pr_no", "pr_line", "created_at", "requester", "department", "plant", "item_code", "description",
              "quantity", "uom", "estimated_unit_price", "need_by_date", "urgency"]


def pr_lines_from_csv(text: str) -> list[PRLine]:
    out = []
    for i, r in enumerate(_rows(text)):
        try:
            line_no = int(float(r.get("pr_line") or 1))
        except ValueError:
            line_no = i + 1
        out.append(PRLine(
            pr_no=r.get("pr_no", "") or f"ROW-{i + 1}",
            pr_line=line_no,
            created_at=parse_datetime(r.get("created_at")),
            requester=r.get("requester", ""),
            department=r.get("department", ""),
            plant=r.get("plant", "").upper(),
            item_code=r.get("item_code", "").upper(),
            description=r.get("description", ""),
            quantity=_f(r.get("quantity")),
            uom=r.get("uom", "").upper(),
            estimated_unit_price=_f(r.get("estimated_unit_price")),
            need_by_date=parse_date(r.get("need_by_date")),
            urgency=(r.get("urgency") or "Normal").strip().title(),
            raw=r,
        ))
    return out


def dataset_from_dir(kit_dir: str, extra_contracts: dict[str, Contract] | None = None) -> Dataset:
    """Load a kit directory laid out like the Cantill task kit."""
    rd = lambda *p: open(os.path.join(kit_dir, *p), encoding="utf-8").read()  # noqa: E731
    contracts = contracts_from_csv(rd("contracts", "contract_register.csv"), rd("contracts", "contract_lines.csv"))
    if extra_contracts:
        contracts.update(extra_contracts)
    return Dataset(
        items=items_from_csv(rd("master_data", "item_master.csv")),
        suppliers=suppliers_from_csv(rd("master_data", "supplier_master.csv")),
        plants=plants_from_csv(rd("master_data", "plants.csv")),
        pos=pos_from_csv(rd("master_data", "po_history.csv")),
        contracts=contracts,
    )
