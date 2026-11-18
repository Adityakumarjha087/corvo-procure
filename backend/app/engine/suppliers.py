"""Preferred supplier lists (policy section 6) and sourcing suggestions (6.4).

Score (weights live in the policy, defaults in v5.0):
  frequency   POs for the item in the lookback window / the most any listed supplier has   (0..1)
  recency     1.0 if the last PO is within 90 days, 0.5 within 365 days, else 0               (bands)
  contract    1 if the supplier has held a contract for the item that started by the date
  performance mean of on_time_pct/100 and quality_rating/5 from the supplier master
score = w_f*frequency + w_r*recency + w_c*contract + w_p*performance
Ties: higher score, then more recent last PO, then supplier id.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date

from .model import Dataset, Supplier


@dataclass
class RankedSupplier:
    supplier_id: str
    name: str
    rank: int
    score: float
    po_count: int
    last_po_date: str | None
    days_since_last_po: int | None
    recency: float
    frequency: float
    has_contract: bool
    on_time_pct: float
    quality_rating: float
    performance: float
    reference_price: float | None
    reference_source: str | None  # "PO 7300123 (2026-10-07)" or "contract RC-2026-002"
    components: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def eligible(sup: Supplier | None, policy: dict) -> bool:
    if sup is None:
        return False
    el = policy.get("supplier_eligibility", {})
    if sup.status not in el.get("statuses", ["Active"]):
        return False
    if el.get("min_on_time_pct") is not None and sup.on_time_pct < float(el["min_on_time_pct"]):
        return False
    if el.get("min_quality_rating") is not None and sup.quality_rating < float(el["min_quality_rating"]):
        return False
    return True


def performance(sup: Supplier, policy: dict) -> float:
    p = policy.get("preferred_suppliers", {}).get("performance", {})
    wo, wq = float(p.get("on_time_weight", 0.5)), float(p.get("quality_weight", 0.5))
    scale = float(p.get("quality_scale", 5))
    tot = (wo + wq) or 1.0
    return (wo * sup.on_time_pct / 100.0 + wq * sup.quality_rating / scale) / tot


def _recency(days: int | None, bands: list[dict]) -> float:
    if days is None:
        return 0.0
    for b in sorted(bands, key=lambda b: b["max_days"]):
        if days <= b["max_days"]:
            return float(b["score"])
    return 0.0


def preferred_list(ds: Dataset, item_code: str, as_of: date, policy: dict) -> list[RankedSupplier]:
    cfg = policy.get("preferred_suppliers", {})
    lookback = int(cfg.get("lookback_days", 548))
    w = {"frequency": 0.30, "recency": 0.30, "contract": 0.15, "performance": 0.25, **cfg.get("weights", {})}
    bands = cfg.get("recency_bands", [{"max_days": 90, "score": 1.0}, {"max_days": 365, "score": 0.5}])

    pos = ds.pos_for_item(item_code, as_of, lookback)
    by_sup: dict[str, list] = {}
    for p in pos:
        by_sup.setdefault(p.supplier_id, []).append(p)
    contracts_by_sup: dict[str, list] = {}
    if cfg.get("include_contract_holders", True) or w.get("contract"):
        for c in ds.contracts_for_item(item_code):
            if c.start_date and c.start_date <= as_of:
                contracts_by_sup.setdefault(c.supplier_id, []).append(c)

    members = set(by_sup)
    if cfg.get("include_contract_holders", True):
        members |= set(contracts_by_sup)
    members = {s for s in members if eligible(ds.suppliers.get(s), policy)}
    if not members:
        return []
    max_n = max((len(by_sup.get(s, [])) for s in members), default=0) or 1

    out: list[RankedSupplier] = []
    for sid in members:
        sup = ds.suppliers[sid]
        sp = by_sup.get(sid, [])
        last = sp[-1] if sp else None
        days = (as_of - last.po_date).days if last else None
        freq = len(sp) / max_n
        rec = _recency(days, bands)
        has_c = bool(contracts_by_sup.get(sid))
        perf = performance(sup, policy)
        comps = {
            "frequency": round(w["frequency"] * freq, 4),
            "recency": round(w["recency"] * rec, 4),
            "contract": round(w["contract"] * (1.0 if has_c else 0.0), 4),
            "performance": round(w["performance"] * perf, 4),
        }
        if last:
            ref, src = last.unit_price, f"PO {last.po_number} ({last.po_date.isoformat()})"
        elif has_c:
            c = max(contracts_by_sup[sid], key=lambda c: (c.start_date, c.contract_id))
            ref, src = c.lines[item_code].rate, f"contract {c.contract_id}"
        else:
            ref, src = None, None
        out.append(RankedSupplier(
            supplier_id=sid, name=sup.name, rank=0, score=round(sum(comps.values()), 4), po_count=len(sp),
            last_po_date=last.po_date.isoformat() if last else None, days_since_last_po=days, recency=rec,
            frequency=round(freq, 4), has_contract=has_c, on_time_pct=sup.on_time_pct, quality_rating=sup.quality_rating,
            performance=round(perf, 4), reference_price=ref, reference_source=src, components=comps,
        ))
    out.sort(key=lambda r: (-r.score, r.days_since_last_po if r.days_since_last_po is not None else 10**6, r.supplier_id))
    for i, r in enumerate(out, 1):
        r.rank = i
    return out


def suggest(ds: Dataset, item_code: str, category: str, ranked: list[RankedSupplier], count: int, policy: dict) -> list[dict]:
    """6.4: take the preferred list in order, then top up from Active suppliers of the category."""
    out = [{"supplier_id": r.supplier_id, "name": r.name, "source": "preferred", "rank": r.rank, "score": r.score} for r in ranked[:count]]
    if len(out) < count and policy.get("sourcing_suggestions", {}).get("topup_from_category", True):
        have = {o["supplier_id"] for o in out}
        pool = [s for s in ds.suppliers.values() if category in s.categories and s.supplier_id not in have and eligible(s, policy)]
        pool.sort(key=lambda s: (-round(performance(s, policy), 6), s.supplier_id))
        for s in pool[: count - len(out)]:
            out.append({"supplier_id": s.supplier_id, "name": s.name, "source": "category", "rank": None, "score": round(performance(s, policy), 4)})
    return out
