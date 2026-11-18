"""Plain data types the decision engine works on.

The engine never touches the database or HTTP: callers build a ``Dataset`` (from the
DB or straight from the kit CSVs) and pass PR lines plus the policy book in.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class Item:
    item_code: str
    description: str
    uom: str
    category: str
    item_type: str
    standard_price: float


@dataclass(frozen=True)
class Supplier:
    supplier_id: str
    name: str
    city: str
    categories: tuple[str, ...]
    status: str
    on_time_pct: float
    quality_rating: float


@dataclass(frozen=True)
class PO:
    po_number: str
    po_date: date
    supplier_id: str
    item_code: str
    quantity: float
    uom: str
    unit_price: float
    plant: str
    delivered_on_time: bool


@dataclass(frozen=True)
class ContractLine:
    item_code: str
    rate: float
    description: str = ""
    uom: str = ""


@dataclass
class Contract:
    contract_id: str
    supplier_id: str
    supplier_name: str
    start_date: date
    end_date: date
    value_cap: float
    consumed_value: float
    lines: dict[str, ContractLine] = field(default_factory=dict)
    source: str = "register"  # register | pdf | manual


@dataclass
class Dataset:
    items: dict[str, Item]
    suppliers: dict[str, Supplier]
    plants: dict[str, str]
    pos: list[PO]
    contracts: dict[str, Contract]

    def __post_init__(self) -> None:
        self._pos_by_item: dict[str, list[PO]] = {}
        for p in sorted(self.pos, key=lambda p: (p.po_date, p.po_number)):
            self._pos_by_item.setdefault(p.item_code, []).append(p)
        self._dates_by_item = {k: [p.po_date for p in v] for k, v in self._pos_by_item.items()}

    def pos_for_item(self, item_code: str, as_of: date, lookback_days: int) -> list[PO]:
        """POs for an item dated within [as_of - lookback_days, as_of], oldest first."""
        pos = self._pos_by_item.get(item_code, [])
        if not pos:
            return []
        dates = self._dates_by_item[item_code]
        from datetime import timedelta

        lo = bisect.bisect_left(dates, as_of - timedelta(days=lookback_days))
        hi = bisect.bisect_right(dates, as_of)
        return pos[lo:hi]

    def contracts_for_item(self, item_code: str) -> list[Contract]:
        return [c for c in self.contracts.values() if item_code in c.lines]


@dataclass
class PRLine:
    pr_no: str
    pr_line: int
    created_at: datetime | None
    requester: str = ""
    department: str = ""
    plant: str = ""
    item_code: str = ""
    description: str = ""
    quantity: float | None = None
    uom: str = ""
    estimated_unit_price: float | None = None
    need_by_date: date | None = None
    urgency: str = "Normal"
    raw: dict = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, int]:
        return (self.pr_no, self.pr_line)


@dataclass
class PolicyVersionRef:
    """One approved policy version as the engine sees it."""

    version: str
    effective_from: date
    doc: dict
