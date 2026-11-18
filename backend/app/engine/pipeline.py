"""The decision engine: PR lines in, decisions out.

Stages (each reads its parameters from the policy version in force on the requirement date):
  validate -> match items (1) -> club into requirements (2) -> value (3) -> contracts and
  ceilings (4) -> first matching rule (5) -> supplier and price (6) -> consolidate POs (7)
Everything is deterministic: same inputs and policy versions give the same output.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .matcher import ItemMatcher
from .model import Contract, Dataset, PolicyVersionRef, PRLine
from .rules import describe, evaluate, inr
from .suppliers import RankedSupplier, eligible, preferred_list, suggest

OUTPUT_COLUMNS = [
    "pr_no", "pr_line", "resolved_item_code", "group_id", "po_id", "decision", "route", "supplier_id",
    "unit_price", "group_value_inr", "suggested_supplier_ids", "policy_version", "reason",
]


class PolicyBook:
    """Approved policy versions; picks the one in force on a date."""

    def __init__(self, versions: list[PolicyVersionRef], mode: str = "by_date"):
        if not versions:
            raise ValueError("No approved policy version available")
        # Callers pass versions in approval order; a stable sort keeps the later approval last for equal dates.
        self.versions = sorted(versions, key=lambda v: v.effective_from)
        self.mode = mode  # by_date | latest

    def for_date(self, d: date) -> PolicyVersionRef:
        if self.mode == "latest":
            return self.versions[-1]
        cur = self.versions[0]
        for v in self.versions:
            if v.effective_from <= d:
                cur = v
        return cur


@dataclass
class Requirement:
    group_id: str
    item_code: str | None
    plant: str
    lines: list[PRLine]
    is_new_item: bool = False
    policy: PolicyVersionRef | None = None
    decision: str = ""
    route: str = ""
    rule_id: str = ""
    rule_name: str = ""
    supplier_id: str | None = None
    supplier_name: str | None = None
    unit_price: float | None = None
    value: float | None = None
    value_price: float | None = None
    value_basis: str = ""
    contract_id: str | None = None
    suggestions: list[dict] = field(default_factory=list)
    preferred: list[RankedSupplier] = field(default_factory=list)
    facts: dict = field(default_factory=dict)
    trace: list[dict] = field(default_factory=list)
    reason: str = ""
    po_id: str | None = None
    match: dict = field(default_factory=dict)

    @property
    def first(self) -> PRLine:
        return self.lines[0]

    @property
    def req_dt(self) -> datetime:
        return self.first.created_at

    @property
    def req_date(self) -> date:
        return self.first.created_at.date()

    @property
    def quantity(self) -> float:
        return sum(l.quantity or 0 for l in self.lines)

    @property
    def is_emergency(self) -> bool:
        return any((l.urgency or "").lower() == "emergency" for l in self.lines)

    def step(self, clause: str, title: str, detail: str) -> None:
        self.trace.append({"clause": clause, "title": title, "detail": detail})

    def as_dict(self) -> dict:
        return {
            "group_id": self.group_id, "item_code": self.item_code, "plant": self.plant, "is_new_item": self.is_new_item,
            "requirement_date": self.req_dt.isoformat(sep=" ", timespec="minutes"), "quantity": self.quantity,
            "is_emergency": self.is_emergency, "policy_version": self.policy.version if self.policy else None,
            "decision": self.decision, "route": self.route, "rule_id": self.rule_id, "rule_name": self.rule_name,
            "supplier_id": self.supplier_id, "supplier_name": self.supplier_name, "unit_price": self.unit_price,
            "value": self.value, "value_price": self.value_price, "value_basis": self.value_basis,
            "contract_id": self.contract_id, "suggestions": self.suggestions,
            "preferred": [p.as_dict() for p in self.preferred[:8]], "facts": _jsonable(self.facts), "trace": self.trace,
            "reason": self.reason, "po_id": self.po_id, "match": self.match,
            "lines": [{"pr_no": l.pr_no, "pr_line": l.pr_line, "created_at": l.created_at.isoformat(sep=" ", timespec="minutes"),
                       "requester": l.requester, "department": l.department, "description": l.description,
                       "quantity": l.quantity, "uom": l.uom, "need_by_date": l.need_by_date.isoformat() if l.need_by_date else None,
                       "urgency": l.urgency, "estimated_unit_price": l.estimated_unit_price} for l in self.lines],
        }


def _jsonable(d: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in d.items()}


def _r2(v: float | None) -> float | None:
    return None if v is None else round(v + 0.0, 2)


@dataclass
class BatchResult:
    rows: list[dict]
    requirements: list[Requirement]
    purchase_orders: list[dict]
    not_processed: list[dict]
    summary: dict


class Engine:
    def __init__(self, ds: Dataset, book: PolicyBook):
        self.ds = ds
        self.book = book
        self.matcher = ItemMatcher(ds.items)
        self.ceiling_used: dict[str, float] = {}
        self._pref_cache: dict[tuple, list[RankedSupplier]] = {}

    # ------------------------------------------------------------------ helpers
    def preferred(self, item_code: str, d: date, pol: PolicyVersionRef) -> list[RankedSupplier]:
        key = (item_code, d, pol.version)
        if key not in self._pref_cache:
            self._pref_cache[key] = preferred_list(self.ds, item_code, d, pol.doc)
        return self._pref_cache[key]

    def _ceiling_left(self, c: Contract) -> float:
        return c.value_cap - c.consumed_value - self.ceiling_used.get(c.contract_id, 0.0)

    # ------------------------------------------------------------------ stages
    def validate(self, lines: list[PRLine]) -> tuple[list[PRLine], dict]:
        ok, bad, seen = [], {}, set()
        for l in lines:
            why = None
            if l.key in seen:
                why = f"Duplicate PR line {l.pr_no}/{l.pr_line}; the first occurrence was processed."
            elif l.created_at is None:
                why = "Missing or unreadable created_at timestamp, so the line cannot be ordered or dated."
            elif l.plant not in self.ds.plants:
                why = f"Unknown plant '{l.plant or '(blank)'}'; valid plants are {', '.join(sorted(self.ds.plants))}. Requester must correct the plant."
            elif l.quantity is None or l.quantity <= 0:
                why = f"Quantity is {l.quantity if l.quantity is not None else 'missing'}; nothing to buy. Requester must correct the quantity."
            seen.add(l.key)
            if why:
                bad[l.key] = why
            else:
                ok.append(l)
        return ok, bad

    def match_items(self, lines: list[PRLine], bad: dict) -> tuple[list[PRLine], dict]:
        matched, info = [], {}
        for l in lines:
            pol = self.book.for_date(l.created_at.date()).doc
            r = self.matcher.match(l.item_code, l.description, l.uom, float(pol.get("item_matching", {}).get("min_score", 0.72)))
            if r["item_code"] and r.get("ambiguous") and r["method"] == "description":
                c = r["candidates"]
                bad[l.key] = (f"Description '{l.description}' fits more than one item equally well "
                              f"({c[0]['item_code']} {c[0]['description']} / {c[1]['item_code']} {c[1]['description']}); "
                              "requester must confirm the item.")
                continue
            info[l.key] = r
            matched.append(l)
        return matched, info

    def club(self, lines: list[PRLine], info: dict) -> list[Requirement]:
        lines = sorted(lines, key=lambda l: (l.created_at, l.pr_no, l.pr_line))
        reqs: list[Requirement] = []
        open_by_key: dict[tuple, list[Requirement]] = {}
        for l in lines:
            m = info[l.key]
            code = m["item_code"]
            if code is None:
                new_cfg = self.book.for_date(l.created_at.date()).doc.get("item_matching", {}).get("new_item", {})
                if not new_cfg.get("club", False):
                    reqs.append(Requirement("", None, l.plant, [l], is_new_item=True, match=m))
                    continue
            joined = None
            for r in open_by_key.get((code, l.plant), []):
                cfg = self.book.for_date(r.req_date).doc.get("clubbing", {})
                if not cfg.get("enabled", True):
                    continue
                same = cfg.get("same", ["item_code", "plant"])
                if "department" in same and l.department != r.first.department:
                    continue
                if "requester" in same and l.requester != r.first.requester:
                    continue
                if (l.created_at.date() - r.req_date).days > int(cfg.get("creation_window_days", 14)):
                    continue
                if l.need_by_date is None or r.first.need_by_date is None:
                    continue
                if abs((l.need_by_date - r.first.need_by_date).days) > int(cfg.get("need_by_window_days", 7)):
                    continue
                joined = r
                break  # requirements are kept in creation order, so this is the earliest
            if joined:
                joined.lines.append(l)
            else:
                r = Requirement("", code, l.plant, [l], is_new_item=code is None, match=m)
                reqs.append(r)
                open_by_key.setdefault((code, l.plant), []).append(r)
        reqs.sort(key=lambda r: (r.req_dt, r.first.pr_no, r.first.pr_line))
        for i, r in enumerate(reqs, 1):
            r.group_id = f"REQ-{i:04d}"
        return reqs

    def decide(self, r: Requirement) -> None:
        d = r.req_date
        r.policy = pol = self.book.for_date(d)
        P = pol.doc
        ver = pol.version
        m = r.match
        if m.get("method") == "description":
            r.step("1.1", "Item matched", f"'{r.first.description}' matched to {r.item_code} (score {m['score']:.2f}).")
        if len(r.lines) > 1:
            r.step("2.2", "Lines clubbed", f"{len(r.lines)} PR lines for the same item and plant form one requirement: "
                   + ", ".join(f"{l.pr_no}/{l.pr_line}" for l in r.lines) + ".")

        # ---------------- new item (1.2)
        if r.is_new_item:
            cfg = P.get("item_matching", {}).get("new_item", {})
            l = r.first
            r.value_price = l.estimated_unit_price
            r.value = _r2(l.quantity * l.estimated_unit_price) if l.estimated_unit_price is not None else None
            r.value_basis = "requester's estimated unit price" if r.value is not None else "no estimate given"
            r.decision, r.route = cfg.get("decision", "SOURCING_REQUEST"), cfg.get("route", "NEW_ITEM_SOURCING")
            r.rule_id, r.rule_name = cfg.get("clause", "1.2"), "New item"
            cand = m.get("candidates") or []
            near = f" Closest item master entry was {cand[0]['item_code']} {cand[0]['description']} (score {cand[0]['score']:.2f}), below the match threshold." if cand else ""
            val = inr(r.value) if r.value is not None else "unknown (no estimated price; buyer to estimate)"
            r.reason = (f"v{ver} §{r.rule_id}: '{l.description}' is not in the item master, so it is a new item: "
                        f"sourcing request, not clubbed, valued at quantity x requester's estimate = {val}; no supplier suggestions.{near}")
            r.step(r.rule_id, "New item", r.reason)
            r.suggestions = []
            return

        item = self.ds.items[r.item_code]
        qty = r.quantity

        # ---------------- contracts (4.1-4.3)
        ccfg = P.get("contracts", {})
        statuses = set(ccfg.get("supplier_statuses", ["Active"]))
        applicable, excluded = [], []
        for c in self.ds.contracts_for_item(r.item_code):
            sup = self.ds.suppliers.get(c.supplier_id)
            if not (c.start_date <= d <= c.end_date):
                excluded.append(f"{c.contract_id} not valid on {d} ({c.start_date} to {c.end_date})")
            elif not sup or sup.status not in statuses:
                excluded.append(f"{c.contract_id} supplier {c.supplier_id} is {sup.status if sup else 'unknown'}")
            else:
                applicable.append(c)
        usable, out_of_ceiling = [], []
        for c in applicable:
            need = qty * c.lines[r.item_code].rate
            if not ccfg.get("enforce_ceiling", True) or self._ceiling_left(c) + 1e-6 >= need:
                usable.append(c)
            else:
                out_of_ceiling.append(f"{c.contract_id} ceiling left {inr(self._ceiling_left(c))} < {inr(need)} needed")
        usable.sort(key=lambda c: (c.lines[r.item_code].rate, -self._ceiling_left(c), c.contract_id))
        chosen = usable[0] if usable else None
        if excluded:
            r.step("4.1", "Contracts not applicable", "; ".join(excluded) + ".")
        if out_of_ceiling:
            r.step("4.2", "Contracts out of ceiling", "; ".join(out_of_ceiling) + ".")
        if chosen:
            r.step("4.3", "Contract available", f"{chosen.contract_id} ({chosen.supplier_id}) at {chosen.lines[r.item_code].rate}; ceiling left {inr(self._ceiling_left(chosen))}.")

        # ---------------- value (3.1)
        vcfg = P.get("valuation", {})
        price, basis = None, ""
        for src in vcfg.get("order", ["contract", "last_po", "standard_price"]):
            if src == "contract":
                if chosen:
                    price, basis = chosen.lines[r.item_code].rate, f"rate of contract {chosen.contract_id} that will be used (3.1a)"
                elif applicable:
                    low = min(applicable, key=lambda c: (c.lines[r.item_code].rate, c.contract_id))
                    price, basis = low.lines[r.item_code].rate, f"lowest applicable contract rate, {low.contract_id} (3.1a; all applicable contracts out of ceiling)"
            elif src == "last_po":
                pos = self.ds.pos_for_item(r.item_code, d, int(vcfg.get("last_po_lookback_days", 365)))
                if vcfg.get("last_po_active_suppliers_only"):
                    pos = [p for p in pos if eligible(self.ds.suppliers.get(p.supplier_id), P)]
                if pos:
                    p = pos[-1]
                    price, basis = p.unit_price, f"most recent PO {p.po_number} ({p.po_date}, {p.supplier_id}) in the last {vcfg.get('last_po_lookback_days', 365)} days (3.1b)"
            elif src == "standard_price":
                price, basis = item.standard_price, "item master standard price (3.1c)"
            if price is not None:
                break
        r.value_price, r.value_basis = price, basis
        r.value = _r2(qty * price)
        r.step(vcfg.get("clause", "3.1"), "Requirement valued", f"{qty:g} {item.uom} x {price} = {inr(r.value)}; price is the {basis}.")

        # ---------------- facts
        all_pos = self.ds.pos_for_item(r.item_code, d, 100000)
        active_pos = [p for p in all_pos if eligible(self.ds.suppliers.get(p.supplier_id), P)]
        last_active = active_pos[-1] if active_pos else None
        ranked = self.preferred(r.item_code, d, pol)
        r.preferred = ranked
        need_bys = [l.need_by_date for l in r.lines if l.need_by_date]
        r.facts = {
            "item_code": r.item_code, "item_type": item.item_type, "category": item.category, "plant": r.plant,
            "value": r.value, "quantity": qty, "unit_price": price, "is_emergency": r.is_emergency,
            "urgency": "Emergency" if r.is_emergency else "Normal",
            "contract_usable": chosen is not None, "contract_applicable": bool(applicable),
            "contract_id": chosen.contract_id if chosen else None,
            "contract_supplier_id": chosen.supplier_id if chosen else None,
            "days_since_active_purchase": (d - last_active.po_date).days if last_active else None,
            "days_since_any_purchase": (d - all_pos[-1].po_date).days if all_pos else None,
            "active_purchase_count_365": sum(1 for p in active_pos if (d - p.po_date).days <= 365),
            "is_new_item": False, "lead_time_days": (min(need_bys) - d).days if need_bys else None,
            "line_count": len(r.lines), "departments": sorted({l.department for l in r.lines if l.department}),
            "requesters": sorted({l.requester for l in r.lines if l.requester}),
            "preferred_supplier_count": len(ranked), "top_supplier_id": ranked[0].supplier_id if ranked else None,
            "top_supplier_on_time_pct": ranked[0].on_time_pct if ranked else None,
            "top_supplier_quality": ranked[0].quality_rating if ranked else None,
            "requirement_date": d.isoformat(), "month": d.month,
        }

        # ---------------- rules (5)
        rule = None
        for cand in P.get("rules", []):
            if cand.get("enabled", True) is False:
                continue
            if evaluate(cand.get("when"), r.facts):
                rule = cand
                break
        if rule is None:
            rule = P.get("fallback") or {"id": "fallback", "name": "No rule matched", "then": {"decision": "SOURCING_REQUEST", "route": "RFQ", "supplier": {"mode": "suggest", "count": 3}}}
        self._apply_outcome(r, rule, chosen, ranked, item, ver)

    def _apply_outcome(self, r: Requirement, rule: dict, chosen: Contract | None, ranked: list[RankedSupplier], item, ver: str,
                       fallback_note: str = "") -> None:
        P = r.policy.doc
        then = rule.get("then", {})
        sup_cfg = then.get("supplier", {}) or {}
        mode = sup_cfg.get("mode", "none")
        r.rule_id, r.rule_name = str(rule.get("id", "")), rule.get("name", "")
        r.decision, r.route = then.get("decision", "SOURCING_REQUEST"), then.get("route", "RFQ")
        cond_txt = describe(rule.get("when"))
        detail = ""
        if r.decision == "PO":
            if mode == "contract":
                if not chosen:
                    return self._fallback(r, rule, ranked, item, ver, "rule needs a usable contract but none is available")
                rate = chosen.lines[r.item_code].rate
                left_before = self._ceiling_left(chosen)
                self.ceiling_used[chosen.contract_id] = self.ceiling_used.get(chosen.contract_id, 0.0) + r.quantity * rate
                r.contract_id, r.supplier_id, r.unit_price = chosen.contract_id, chosen.supplier_id, rate
                r.supplier_name = self.ds.suppliers[chosen.supplier_id].name
                src = " (signed PDF, not yet in the register)" if chosen.source == "pdf" else ""
                detail = (f"Contract {chosen.contract_id}{src} with {chosen.supplier_id} {r.supplier_name} at {rate}, valid "
                          f"{chosen.start_date} to {chosen.end_date}; ceiling {inr(chosen.value_cap)}, left before this "
                          f"{inr(left_before)}, after {inr(self._ceiling_left(chosen))}.")
            elif mode in ("preferred", "fixed"):
                pick = None
                if mode == "fixed":
                    pick = next((p for p in ranked if p.supplier_id == sup_cfg.get("supplier_id")), None)
                elif sup_cfg.get("pick") == "lowest_price":
                    among = [p for p in ranked[: int(sup_cfg.get("among", 3))] if p.reference_price is not None]
                    pick = min(among, key=lambda p: (p.reference_price, p.rank)) if among else None
                else:
                    rank = int(sup_cfg.get("rank", 1))
                    pick = ranked[rank - 1] if len(ranked) >= rank else None
                if not pick or pick.reference_price is None:
                    return self._fallback(r, rule, ranked, item, ver, "no eligible preferred supplier with a reference price")
                r.supplier_id, r.supplier_name, r.unit_price = pick.supplier_id, pick.name, pick.reference_price
                detail = (f"Supplier {pick.supplier_id} {pick.name} is ranked {pick.rank} on the preferred list (§6, score "
                          f"{pick.score:.3f}: {pick.po_count} POs, last {pick.last_po_date or 'never'}, contract "
                          f"{'yes' if pick.has_contract else 'no'}, on-time {pick.on_time_pct:g}%, quality {pick.quality_rating:g}); "
                          f"price {pick.reference_price} is its reference price from {pick.reference_source} (6.3).")
            else:
                return self._fallback(r, rule, ranked, item, ver, f"PO rule has unsupported supplier mode '{mode}'")
        elif r.decision == "SOURCING_REQUEST":
            count = int(sup_cfg.get("count", 0)) if mode == "suggest" else 0
            r.suggestions = suggest(self.ds, r.item_code, item.category, ranked, count, P) if count else []
            if count:
                names = ", ".join(s["supplier_id"] + ("" if s["source"] == "preferred" else "*") for s in r.suggestions)
                detail = f"Suggested suppliers (§6.4): {names or 'none available'}" + (" (* = topped up from category)" if any(s['source'] == 'category' for s in r.suggestions) else "") + "."
                if len(r.suggestions) < count:
                    detail += f" Only {len(r.suggestions)} eligible supplier(s) found for {count} requested."
        note = then.get("note")
        r.reason = (f"v{ver} §{r.rule_id} {r.rule_name}: {cond_txt}. Value {inr(r.value)} "
                    f"({r.value_basis}). {detail}{(' ' + note) if note else ''}{(' ' + fallback_note) if fallback_note else ''}").strip()
        r.step(r.rule_id, f"Rule {r.rule_id} applies: {r.route}", f"{rule.get('name', '')}: {cond_txt}. {detail}".strip())

    def _fallback(self, r, rule, ranked, item, ver, why):
        P = r.policy.doc
        fb = P.get("fallback") or {"id": "fallback", "name": "Fallback", "then": {"decision": "SOURCING_REQUEST", "route": "RFQ", "supplier": {"mode": "suggest", "count": 3}}}
        r.step(str(rule.get("id")), "Rule could not be applied", f"Rule {rule.get('id')} matched but {why}; using the fallback.")
        if fb.get("then", {}).get("decision") == "PO":
            fb = {"id": "fallback", "name": "Fallback", "then": {"decision": "SOURCING_REQUEST", "route": "RFQ", "supplier": {"mode": "suggest", "count": 3}}}
        return self._apply_outcome(r, fb, None, ranked, item, ver, fallback_note=f"(Rule {rule.get('id')} matched but {why}.)")

    def consolidate(self, reqs: list[Requirement]) -> list[dict]:
        pos: list[dict] = []
        for r in sorted([r for r in reqs if r.decision == "PO"], key=lambda r: (r.req_dt, r.group_id)):
            cfg = r.policy.doc.get("consolidation", {})
            target = None
            if cfg.get("enabled", True):
                keys = cfg.get("same", ["supplier_id", "plant", "route"])
                win = timedelta(hours=float(cfg.get("window_hours", 24)))
                for po in pos:
                    if all(po[k] == getattr(r, k) for k in keys) and timedelta(0) <= r.req_dt - po["_first_dt"] <= win:
                        target = po
                        break
            if target is None:
                target = {"po_id": f"PO-{len(pos) + 1:04d}", "supplier_id": r.supplier_id, "supplier_name": r.supplier_name,
                          "plant": r.plant, "route": r.route, "_first_dt": r.req_dt, "group_ids": [], "value": 0.0, "lines": []}
                pos.append(target)
            else:
                r.step(cfg.get("clause", "7"), "Consolidated", f"Added to {target['po_id']} with {', '.join(target['group_ids'])}: same supplier, plant and route within {cfg.get('window_hours', 24)} hours (7.1).")
            target["group_ids"].append(r.group_id)
            target["value"] = round(target["value"] + (r.unit_price or 0) * r.quantity, 2)
            target["lines"].append({"group_id": r.group_id, "item_code": r.item_code, "quantity": r.quantity, "unit_price": r.unit_price})
            r.po_id = target["po_id"]
        for po in pos:
            po["created_from"] = po.pop("_first_dt").isoformat(sep=" ", timespec="minutes")
        return pos

    # ------------------------------------------------------------------ main
    def run(self, lines: list[PRLine]) -> BatchResult:
        valid, bad = self.validate(lines)
        matched, info = self.match_items(valid, bad)
        reqs = self.club(matched, info)
        for r in reqs:  # requirement-date order: ceilings are consumed in this order (4.2)
            self.decide(r)
        pos = self.consolidate(reqs)
        by_line = {l.key: r for r in reqs for l in r.lines}
        rows = []
        for l in lines:
            r = by_line.get(l.key)
            if r is None:
                pol = self.book.for_date(l.created_at.date()) if l.created_at else self.book.versions[-1]
                rows.append({"pr_no": l.pr_no, "pr_line": l.pr_line, "resolved_item_code": "", "group_id": "", "po_id": "",
                             "decision": "NOT_PROCESSED", "route": "NOT_PROCESSED", "supplier_id": "", "unit_price": "",
                             "group_value_inr": "", "suggested_supplier_ids": "", "policy_version": pol.version,
                             "reason": bad.get(l.key, "Not processed.")})
                continue
            rows.append({
                "pr_no": l.pr_no, "pr_line": l.pr_line, "resolved_item_code": r.item_code or "NEW", "group_id": r.group_id,
                "po_id": r.po_id or "", "decision": r.decision, "route": r.route,
                "supplier_id": r.supplier_id or "" if r.decision == "PO" else "",
                "unit_price": _r2(r.unit_price) if r.decision == "PO" and r.unit_price is not None else "",
                "group_value_inr": _r2(r.value) if r.value is not None else "",
                "suggested_supplier_ids": ";".join(s["supplier_id"] for s in r.suggestions) if r.decision != "PO" else "",
                "policy_version": r.policy.version, "reason": r.reason,
            })
        rows.sort(key=lambda x: (x["pr_no"], int(x["pr_line"])))
        summary = {
            "lines": len(lines), "requirements": len(reqs), "purchase_orders": len(pos),
            "not_processed": sum(1 for x in rows if x["decision"] == "NOT_PROCESSED"),
            "routes": _count(r.route for r in reqs), "policy_versions": sorted({r.policy.version for r in reqs}),
            "total_value": round(sum(r.value or 0 for r in reqs), 2),
        }
        return BatchResult(rows, reqs, pos, [{"pr_no": k[0], "pr_line": k[1], "reason": v} for k, v in bad.items()], summary)


def _count(it) -> dict:
    out: dict = {}
    for x in it:
        out[x] = out.get(x, 0) + 1
    return out


def run_batch(ds: Dataset, lines: list[PRLine], versions: list[PolicyVersionRef], mode: str = "by_date") -> BatchResult:
    return Engine(ds, PolicyBook(versions, mode)).run(lines)
