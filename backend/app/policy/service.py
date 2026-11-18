"""Policy versions: validation, edit operations, plain-language diff, activation."""
from __future__ import annotations

import copy
import json
import os
from datetime import date

from ..engine.model import PolicyVersionRef
from ..engine.rules import FACTS, OPS, describe, facts_used, inr

DEFAULT_POLICY_PATH = os.path.join(os.path.dirname(__file__), "corvo_v5_0.json")

DECISIONS = {"PO", "SOURCING_REQUEST", "NOT_PROCESSED"}
SUPPLIER_MODES = {"contract", "preferred", "suggest", "none", "fixed"}
KNOWN_ROUTES = ["CONTRACT_PO", "EMERGENCY_PO", "SPOT_PO", "RFQ", "RFP", "CAPEX_SOURCING", "NEW_ITEM_SOURCING", "NOT_PROCESSED"]

# Human labels for parameters; used in the change preview.
PARAM_LABELS = {
    "item_matching.min_score": ("Item match threshold", ""),
    "item_matching.new_item.route": ("New item route", ""),
    "item_matching.new_item.club": ("Club new-item lines", ""),
    "clubbing.enabled": ("Clubbing of similar PR lines", ""),
    "clubbing.same": ("Lines club when they share", ""),
    "clubbing.creation_window_days": ("Clubbing window from the first line's creation", " days"),
    "clubbing.need_by_window_days": ("Clubbing need-by tolerance (either side)", " days"),
    "valuation.order": ("Valuation price order", ""),
    "valuation.last_po_lookback_days": ("Valuation look-back for last PO price", " days"),
    "valuation.last_po_active_suppliers_only": ("Valuation uses only Active suppliers' POs", ""),
    "contracts.supplier_statuses": ("Contract supplier must be", ""),
    "contracts.enforce_ceiling": ("Enforce contract value ceilings", ""),
    "supplier_eligibility.statuses": ("Supplier statuses allowed for POs and suggestions", ""),
    "supplier_eligibility.min_on_time_pct": ("Minimum on-time % for POs and suggestions", "%"),
    "supplier_eligibility.min_quality_rating": ("Minimum quality rating for POs and suggestions", ""),
    "preferred_suppliers.lookback_days": ("Preferred list look-back", " days"),
    "preferred_suppliers.include_contract_holders": ("Contract holders join the preferred list", ""),
    "preferred_suppliers.weights.frequency": ("Ranking weight: purchase frequency", ""),
    "preferred_suppliers.weights.recency": ("Ranking weight: recency", ""),
    "preferred_suppliers.weights.contract": ("Ranking weight: held a contract", ""),
    "preferred_suppliers.weights.performance": ("Ranking weight: delivery and quality", ""),
    "sourcing_suggestions.topup_from_category": ("Top up suggestions from the item category", ""),
    "consolidation.enabled": ("PO consolidation", ""),
    "consolidation.same": ("Requirements share a PO when they have the same", ""),
    "consolidation.window_hours": ("PO consolidation window", " hours"),
}


def load_default() -> dict:
    with open(DEFAULT_POLICY_PATH, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- validation
def _check_cond(cond, path: str, errors: list[str]) -> None:
    if cond is None:
        return
    if not isinstance(cond, dict):
        errors.append(f"{path}: condition must be an object")
        return
    groups = [k for k in ("all", "any", "not") if k in cond]
    if groups:
        for g in groups:
            if g == "not":
                _check_cond(cond["not"], f"{path}.not", errors)
            elif not isinstance(cond[g], list):
                errors.append(f"{path}.{g}: must be a list")
            else:
                for i, c in enumerate(cond[g]):
                    _check_cond(c, f"{path}.{g}[{i}]", errors)
        return
    if cond.get("fact") not in FACTS:
        errors.append(f"{path}: unknown fact '{cond.get('fact')}'. Known facts: {', '.join(FACTS)}")
    if cond.get("op", "eq") not in OPS:
        errors.append(f"{path}: unknown operator '{cond.get('op')}'")
    if cond.get("op") not in ("exists", "not_exists") and "value" not in cond:
        errors.append(f"{path}: missing value")


def validate(doc: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["Policy must be a JSON object"]
    if not doc.get("version"):
        errors.append("version is required")
    try:
        date.fromisoformat(str(doc.get("effective_from")))
    except ValueError:
        errors.append("effective_from must be a date (YYYY-MM-DD)")
    rules = doc.get("rules")
    if not isinstance(rules, list) or not rules:
        errors.append("rules must be a non-empty list")
        rules = []
    seen = set()
    for i, r in enumerate(rules):
        p = f"rules[{i}]"
        rid = str(r.get("id", ""))
        if not rid:
            errors.append(f"{p}: id is required")
        elif rid in seen:
            errors.append(f"{p}: duplicate rule id {rid}")
        seen.add(rid)
        _check_cond(r.get("when"), f"{p}.when", errors)
        then = r.get("then") or {}
        if then.get("decision") not in DECISIONS:
            errors.append(f"{p}.then.decision must be one of {sorted(DECISIONS)}")
        if not then.get("route"):
            errors.append(f"{p}.then.route is required")
        mode = (then.get("supplier") or {}).get("mode", "none")
        if mode not in SUPPLIER_MODES:
            errors.append(f"{p}.then.supplier.mode must be one of {sorted(SUPPLIER_MODES)}")
        if then.get("decision") == "PO" and mode not in ("contract", "preferred", "fixed"):
            errors.append(f"{p}: a PO rule needs supplier mode contract, preferred or fixed")
        if mode == "suggest":
            try:
                if int(then["supplier"].get("count", 0)) < 0:
                    raise ValueError
            except (TypeError, ValueError):
                errors.append(f"{p}.then.supplier.count must be a whole number")
    for key in ("clubbing.creation_window_days", "clubbing.need_by_window_days", "valuation.last_po_lookback_days",
                "preferred_suppliers.lookback_days", "consolidation.window_hours"):
        v = get_path(doc, key)
        if v is not None and not isinstance(v, (int, float)):
            errors.append(f"{key} must be a number")
    return errors


# ---------------------------------------------------------------- edit operations (what the AI produces)
def get_path(doc: dict, path: str):
    cur = doc
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def set_path(doc: dict, path: str, value) -> None:
    parts = path.split(".")
    cur = doc
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


def apply_operations(base: dict, ops: list[dict]) -> tuple[dict, list[str]]:
    """Apply edit operations; return (new_doc, problems). Unknown or failing ops are reported, not silently dropped."""
    doc = copy.deepcopy(base)
    problems: list[str] = []
    for n, op in enumerate(ops, 1):
        kind = op.get("op")
        try:
            if kind == "set_param":
                path = op["path"]
                if path.startswith("rules") or path.startswith("fallback"):
                    raise ValueError("use rule operations to change rules")
                set_path(doc, path, op.get("value"))
            elif kind in ("add_rule", "update_rule"):
                rule = op["rule"]
                rules = doc.setdefault("rules", [])
                if kind == "update_rule":
                    rid = str(op.get("rule_id") or rule.get("id"))
                    idx = next((i for i, r in enumerate(rules) if str(r.get("id")) == rid), None)
                    if idx is None:
                        raise ValueError(f"rule {rid} not found")
                    merged = {**rules[idx], **rule}
                    rules[idx] = merged
                else:
                    if any(str(r.get("id")) == str(rule.get("id")) for r in rules):
                        raise ValueError(f"rule id {rule.get('id')} already exists")
                    pos = _position(rules, op)
                    rules.insert(pos, rule)
            elif kind == "remove_rule":
                rid = str(op["rule_id"])
                before = len(doc.get("rules", []))
                doc["rules"] = [r for r in doc.get("rules", []) if str(r.get("id")) != rid]
                if len(doc["rules"]) == before:
                    raise ValueError(f"rule {rid} not found")
            elif kind == "move_rule":
                rid = str(op["rule_id"])
                rules = doc.get("rules", [])
                idx = next((i for i, r in enumerate(rules) if str(r.get("id")) == rid), None)
                if idx is None:
                    raise ValueError(f"rule {rid} not found")
                rule = rules.pop(idx)
                rules.insert(_position(rules, op), rule)
            elif kind == "set_meta":
                for k in ("version", "effective_from", "title"):
                    if op.get(k):
                        doc[k] = op[k]
            else:
                raise ValueError(f"unknown operation '{kind}'")
        except (KeyError, ValueError, TypeError) as e:
            problems.append(f"Operation {n} ({kind}): {e}")
    return doc, problems


def _position(rules: list[dict], op: dict) -> int:
    ids = [str(r.get("id")) for r in rules]
    if op.get("before") and str(op["before"]) in ids:
        return ids.index(str(op["before"]))
    if op.get("after") and str(op["after"]) in ids:
        return ids.index(str(op["after"])) + 1
    if isinstance(op.get("index"), int):
        return max(0, min(op["index"], len(rules)))
    return len(rules) - 0 if not rules else _before_value_ladder(rules)


def _before_value_ladder(rules: list[dict]) -> int:
    """Default insertion point: before the first pure value-limit sourcing rule, so new specific rules take priority."""
    for i, r in enumerate(rules):
        if (r.get("then") or {}).get("decision") == "SOURCING_REQUEST" and facts_used(r.get("when")) <= {"value"}:
            return i
    return len(rules)


# ---------------------------------------------------------------- plain-language diff
def outcome_text(then: dict) -> str:
    sup = then.get("supplier") or {}
    mode = sup.get("mode", "none")
    route = then.get("route", "?")
    if mode == "contract":
        s = "contract supplier at contract rate"
    elif mode == "preferred":
        s = ("cheapest of the top %s preferred suppliers" % sup.get("among", 3)) if sup.get("pick") == "lowest_price" else f"preferred supplier #{sup.get('rank', 1)} at its reference price"
    elif mode == "fixed":
        s = f"supplier {sup.get('supplier_id')}"
    elif mode == "suggest":
        s = f"suggest {sup.get('count', 0)} suppliers"
    else:
        s = "no supplier"
    return f"{route} ({s})"


def rule_text(r: dict) -> str:
    return f"Rule {r.get('id')} “{r.get('name', '')}”: when {describe(r.get('when'))} → {outcome_text(r.get('then') or {})}"


def _fmt(path: str, v) -> str:
    if v is None:
        return "not set"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, list):
        return ", ".join(str(x) for x in v) or "none"
    if isinstance(v, dict):
        return json.dumps(v)
    unit = PARAM_LABELS.get(path, ("", ""))[1]
    return f"{v:g}{unit}" if isinstance(v, (int, float)) else f"{v}{unit}"


def _leaves(d, prefix=""):
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            if prefix == "" and k in ("rules", "fallback", "version", "effective_from", "title", "policy_id", "currency"):
                continue
            if k == "clause":
                continue
            p = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict) and not (p == "preferred_suppliers.recency_bands"):
                out.update(_leaves(v, p))
            else:
                out[p] = v
    return out


def diff(old: dict, new: dict) -> list[dict]:
    changes: list[dict] = []
    if old.get("version") != new.get("version"):
        changes.append({"kind": "meta", "text": f"Version {old.get('version')} → {new.get('version')}"})
    if old.get("effective_from") != new.get("effective_from"):
        changes.append({"kind": "meta", "text": f"Effective from {new.get('effective_from')} (was {old.get('effective_from')})"})
    lo, ln = _leaves(old), _leaves(new)
    for p in sorted(set(lo) | set(ln)):
        if lo.get(p) != ln.get(p):
            label = PARAM_LABELS.get(p, (p.replace("_", " ").replace(".", " › "), ""))[0]
            changes.append({"kind": "param", "path": p, "before": lo.get(p), "after": ln.get(p),
                            "text": f"{label}: {_fmt(p, lo.get(p))} → {_fmt(p, ln.get(p))}"})
    orules = {str(r.get("id")): r for r in old.get("rules", [])}
    nrules = {str(r.get("id")): r for r in new.get("rules", [])}
    norder = [str(r.get("id")) for r in new.get("rules", [])]
    for i, rid in enumerate(norder):
        r = nrules[rid]
        if rid not in orules:
            pos = f"checked after rule {norder[i - 1]}" if i else "checked first"
            changes.append({"kind": "rule_added", "rule_id": rid, "text": f"New {rule_text(r)} ({pos})."})
        elif r != orules[rid]:
            o = orules[rid]
            parts = []
            if o.get("when") != r.get("when"):
                parts.append(f"condition was “{describe(o.get('when'))}”, now “{describe(r.get('when'))}”")
            if o.get("then") != r.get("then"):
                parts.append(f"outcome was {outcome_text(o.get('then') or {})}, now {outcome_text(r.get('then') or {})}")
            if o.get("name") != r.get("name") and not parts:
                parts.append(f"renamed to “{r.get('name')}”")
            if o.get("enabled", True) != r.get("enabled", True):
                parts.append("now disabled" if r.get("enabled") is False else "now enabled")
            changes.append({"kind": "rule_changed", "rule_id": rid, "text": f"Rule {rid} “{r.get('name', '')}” changed: " + "; ".join(parts) + "."})
    for rid, r in orules.items():
        if rid not in nrules:
            changes.append({"kind": "rule_removed", "rule_id": rid, "text": f"Removed {rule_text(r)}."})
    common_old = [str(r.get("id")) for r in old.get("rules", []) if str(r.get("id")) in nrules]
    common_new = [x for x in norder if x in orules]
    if common_old != common_new:
        changes.append({"kind": "rule_order", "text": "Rule order is now: " + " → ".join(norder) + "."})
    if old.get("fallback") != new.get("fallback"):
        changes.append({"kind": "rule_changed", "rule_id": "fallback",
                        "text": f"Fallback changed to {outcome_text((new.get('fallback') or {}).get('then') or {})}."})
    return changes


def bump_version(v: str) -> str:
    try:
        major, minor = v.split(".")[:2]
        return f"{major}.{int(minor) + 1}"
    except ValueError:
        return v + ".1"


def to_ref(pv) -> PolicyVersionRef:
    return PolicyVersionRef(pv.version, pv.effective_from, pv.document)


def summarize_rules(doc: dict) -> list[str]:
    return [rule_text(r) for r in doc.get("rules", [])]


__all__ = ["validate", "apply_operations", "diff", "load_default", "bump_version", "to_ref", "rule_text", "inr", "KNOWN_ROUTES"]
