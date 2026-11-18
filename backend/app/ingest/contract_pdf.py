"""Extract a rate contract from its signed PDF.

Deterministic regex extraction first (works on the standard Corvo template); the API layer can
fall back to the AI extractor for unusual layouts. The buyer always reviews before saving.
"""
from __future__ import annotations

import io
import re

from pypdf import PdfReader

from ..engine.loaders import parse_date


def pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def _num(s: str) -> float:
    return float(s.replace(",", "").strip())


def extract_contract(text: str) -> dict:
    """Return {contract_id, supplier_id, supplier_name, start_date, end_date, value_cap, lines:[...], warnings:[...]}."""
    flat = re.sub(r"\s+", " ", text)
    warnings: list[str] = []
    out: dict = {"lines": [], "warnings": warnings, "consumed_value": 0.0, "source": "pdf"}

    m = re.search(r"Contract\s*No\.?\s*[:\-]?\s*([A-Z]{1,4}-\d{4}-\d{2,4})", flat, re.I)
    out["contract_id"] = m.group(1).upper() if m else None
    m = re.search(r"and\s+(.+?),\s*[A-Za-z .]+\(\s*Supplier\s*ID\s*(S\d+)\s*\)", flat, re.I)
    if m:
        out["supplier_name"], out["supplier_id"] = m.group(1).strip(), m.group(2).upper()
    else:
        m = re.search(r"Supplier\s*ID\s*(S\d+)", flat, re.I)
        out["supplier_id"] = m.group(1).upper() if m else None
        out["supplier_name"] = None
    m = re.search(r"valid\s+from\s+(\S+)\s+to\s+(\S+)", flat, re.I)
    out["start_date"] = parse_date(m.group(1).strip(" ,(")) if m else None
    out["end_date"] = parse_date(m.group(2).strip(" ,(")) if m else None
    m = re.search(r"(?:not\s+exceed|ceiling[^0-9]{0,40})\s*(?:INR|Rs\.?|₹)\s*([\d,]+(?:\.\d+)?)", flat, re.I)
    out["value_cap"] = _num(m.group(1)) if m else None

    for lm in re.finditer(r"(ITM-\d{3,6})\s+(.+?)\s+([A-Z]{2,5})\s+([\d,]+\.\d{1,4}|[\d,]+)(?=\s+(?:\d+\s+ITM-|For\s|$))", flat):
        out["lines"].append({"item_code": lm.group(1), "description": lm.group(2).strip(), "uom": lm.group(3), "rate": _num(lm.group(4))})

    for k in ("contract_id", "supplier_id", "start_date", "end_date", "value_cap"):
        if not out.get(k):
            warnings.append(f"Could not read {k.replace('_', ' ')} from the PDF; please fill it in.")
    if not out["lines"]:
        warnings.append("No item lines found in Schedule A; please add them.")
    if out.get("start_date") and out.get("end_date") and out["end_date"] < out["start_date"]:
        warnings.append("End date is before start date.")
    return out


def extract_contract_pdf(data: bytes) -> dict:
    return extract_contract(pdf_text(data))
