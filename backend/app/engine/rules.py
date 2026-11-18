"""Generic condition evaluator for policy rules.

A condition is either a leaf ``{"fact", "op", "value"}`` or a group ``{"all": [...]}``,
``{"any": [...]}`` or ``{"not": {...}}``. Facts are computed per requirement by the pipeline;
new facts and operators are the only extension points that need code, so policy changes that
recombine them (new limits, plant-only rules, category rules, reordering) are pure data.
"""
from __future__ import annotations

from typing import Any

# Facts the engine computes for every requirement. Exposed to the policy editor and the AI.
FACTS: dict[str, str] = {
    "item_code": "Item code (e.g. ITM-1009)",
    "item_type": "Item type from the item master: Material, Service or Capex",
    "category": "Item category (e.g. Fasteners, Safety & PPE)",
    "plant": "Plant code (PUN1, CHK1)",
    "value": "Requirement value in INR (policy 3.1)",
    "quantity": "Total quantity of the requirement",
    "unit_price": "Unit price used for valuation",
    "is_emergency": "True if any line in the requirement is marked Emergency",
    "urgency": "Emergency or Normal",
    "contract_usable": "A rate contract applies and has ceiling left (4.1-4.3)",
    "contract_applicable": "A rate contract covers the item on the requirement date (ignoring ceiling)",
    "contract_id": "Contract that would be used",
    "contract_supplier_id": "Supplier of the contract that would be used",
    "days_since_active_purchase": "Days since the item was last bought from an Active supplier (empty if never)",
    "days_since_any_purchase": "Days since the item was last bought from any supplier (empty if never)",
    "active_purchase_count_365": "Number of POs for the item from Active suppliers in the last 365 days",
    "is_new_item": "True if the item is not in the item master",
    "lead_time_days": "Days from requirement date to the earliest need-by date",
    "line_count": "Number of PR lines clubbed into the requirement",
    "departments": "Departments that raised the lines (list)",
    "requesters": "Requesters who raised the lines (list)",
    "preferred_supplier_count": "Number of suppliers on the item's preferred list",
    "top_supplier_id": "1st preferred supplier",
    "top_supplier_on_time_pct": "On-time % of the 1st preferred supplier",
    "top_supplier_quality": "Quality rating of the 1st preferred supplier",
    "requirement_date": "Requirement date (YYYY-MM-DD)",
    "month": "Month number of the requirement date (1-12)",
}

OPS = {
    "eq": "is", "ne": "is not", "lt": "is below", "lte": "is at most", "gt": "is above", "gte": "is at least",
    "in": "is one of", "not_in": "is not one of", "between": "is between", "contains": "contains",
    "exists": "is known", "not_exists": "is unknown",
}


def _cmp(a: Any, op: str, b: Any) -> bool:
    if op == "exists":
        return a is not None and a != ""
    if op == "not_exists":
        return a is None or a == ""
    if op in ("eq", "ne"):
        eq = (str(a).lower() == str(b).lower()) if isinstance(a, str) or isinstance(b, str) else a == b
        return eq if op == "eq" else not eq
    if op in ("in", "not_in"):
        vals = b if isinstance(b, (list, tuple)) else [b]
        if isinstance(a, (list, tuple)):
            hit = any(str(x).lower() in {str(v).lower() for v in vals} for x in a)
        else:
            hit = str(a).lower() in {str(v).lower() for v in vals}
        return hit if op == "in" else not hit
    if op == "contains":
        if isinstance(a, (list, tuple)):
            return any(str(b).lower() == str(x).lower() for x in a)
        return a is not None and str(b).lower() in str(a).lower()
    if a is None:
        return False  # unknown facts never satisfy a numeric comparison
    try:
        if op == "between":
            lo, hi = b
            return float(lo) <= float(a) <= float(hi)
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        fa, fb = str(a), str(b)  # dates as ISO strings compare correctly
    return {"lt": fa < fb, "lte": fa <= fb, "gt": fa > fb, "gte": fa >= fb}.get(op, False)


def evaluate(cond: dict | None, facts: dict) -> bool:
    if not cond:
        return True
    if "all" in cond:
        return all(evaluate(c, facts) for c in cond["all"])
    if "any" in cond:
        return any(evaluate(c, facts) for c in cond["any"])
    if "not" in cond:
        return not evaluate(cond["not"], facts)
    return _cmp(facts.get(cond.get("fact")), cond.get("op", "eq"), cond.get("value"))


def _fmt_val(fact: str | None, v: Any) -> str:
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (list, tuple)):
        return ", ".join(_fmt_val(fact, x) for x in v)
    if fact in ("value", "unit_price") and isinstance(v, (int, float)):
        return inr(v)
    if fact and fact.startswith("days_") and isinstance(v, (int, float)):
        return f"{int(v)} days"
    return str(v)


def describe(cond: dict | None) -> str:
    """Plain-language rendering used in reasons, the policy studio and the change preview."""
    if not cond:
        return "always"
    if "all" in cond:
        return " and ".join(describe(c) for c in cond["all"]) or "always"
    if "any" in cond:
        return "(" + " or ".join(describe(c) for c in cond["any"]) + ")"
    if "not" in cond:
        return "not (" + describe(cond["not"]) + ")"
    fact, op, val = cond.get("fact"), cond.get("op", "eq"), cond.get("value")
    label = fact.replace("_", " ") if fact else "?"
    if fact in ("contract_usable", "is_emergency", "is_new_item", "contract_applicable") and op == "eq":
        nice = {"contract_usable": "a rate contract can be used", "is_emergency": "it is an emergency",
                "is_new_item": "it is a new item", "contract_applicable": "a rate contract covers the item"}[fact]
        return nice if val else "not: " + nice
    if fact == "days_since_active_purchase" and op in ("lte", "lt"):
        return f"bought from an Active supplier in the last {int(val)} days"
    if fact == "days_since_active_purchase" and op == "not_exists":
        return "never bought from an Active supplier"
    if op == "between" and isinstance(val, (list, tuple)) and len(val) == 2:
        return f"{label} is between {_fmt_val(fact, val[0])} and {_fmt_val(fact, val[1])}"
    return f"{label} {OPS.get(op, op)} {_fmt_val(fact, val)}".strip()


def inr(v: float | None) -> str:
    """Indian digit grouping: 1234567.8 -> ₹12,34,568."""
    if v is None:
        return "-"
    neg = v < 0
    n = str(int(round(abs(v))))
    if len(n) > 3:
        head, tail = n[:-3], n[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        n = ",".join(parts) + "," + tail
    return ("-" if neg else "") + "₹" + n


def facts_used(cond: dict | None) -> set[str]:
    if not cond:
        return set()
    out: set[str] = set()
    for k in ("all", "any"):
        for c in cond.get(k, []):
            out |= facts_used(c)
    if "not" in cond:
        out |= facts_used(cond["not"])
    if "fact" in cond:
        out.add(cond["fact"])
    return out
