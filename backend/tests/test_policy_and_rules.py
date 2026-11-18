"""Policy-as-data: conditions, edit operations, diff text, and amendments changing decisions without code."""
import copy
from datetime import date

from app.engine.model import PolicyVersionRef
from app.engine.pipeline import run_batch
from app.engine.rules import describe, evaluate, inr
from app.policy import service as pol

from .conftest import needs_kit


def test_conditions():
    f = {"value": 150000, "plant": "CHK1", "category": "Safety & PPE", "days_since_active_purchase": None, "departments": ["IT", "Admin"]}
    assert evaluate({"all": [{"fact": "value", "op": "lt", "value": 200000}, {"fact": "plant", "op": "eq", "value": "chk1"}]}, f)
    assert not evaluate({"fact": "days_since_active_purchase", "op": "lte", "value": 365}, f)  # unknown never passes
    assert evaluate({"fact": "days_since_active_purchase", "op": "not_exists"}, f)
    assert evaluate({"any": [{"fact": "plant", "op": "in", "value": ["PUN1"]}, {"fact": "departments", "op": "contains", "value": "IT"}]}, f)
    assert evaluate({"not": {"fact": "value", "op": "between", "value": [0, 100]}}, f)


def test_describe_and_inr():
    assert inr(1234567.8) == "₹12,34,568"
    assert inr(200000) == "₹2,00,000"
    assert describe({"fact": "days_since_active_purchase", "op": "lte", "value": 365}) == "bought from an Active supplier in the last 365 days"


def test_default_policy_valid(policy):
    assert pol.validate(policy) == []


def test_validation_catches_errors(policy):
    bad = copy.deepcopy(policy)
    bad["rules"][0]["when"] = {"fact": "colour", "op": "eq", "value": "red"}
    bad["rules"][1]["then"]["decision"] = "MAYBE"
    errs = pol.validate(bad)
    assert any("unknown fact" in e for e in errs) and any("decision" in e for e in errs)


def test_operations_and_diff(policy):
    ops = [
        {"op": "set_param", "path": "clubbing.creation_window_days", "value": 21},
        {"op": "update_rule", "rule_id": "5.4", "rule": {"when": {"all": [{"fact": "value", "op": "lt", "value": 300000},
                                                                           {"fact": "days_since_active_purchase", "op": "lte", "value": 365}]}}},
        {"op": "add_rule", "after": "5.2", "rule": {"id": "5.2a", "name": "CHK1 PPE", "when": {"all": [{"fact": "plant", "op": "eq", "value": "CHK1"}]},
                                                    "then": {"decision": "SOURCING_REQUEST", "route": "RFQ", "supplier": {"mode": "suggest", "count": 3}}}},
        {"op": "remove_rule", "rule_id": "5.6"},
        {"op": "set_param", "path": "rules.0", "value": 1},  # rejected: rules change through rule ops
    ]
    doc, problems = pol.apply_operations(policy, ops)
    assert len(problems) == 1
    assert [r["id"] for r in doc["rules"]] == ["5.1", "5.2", "5.2a", "5.3", "5.4", "5.5"]
    texts = " | ".join(c["text"] for c in pol.diff(policy, doc))
    assert "14 days → 21 days" in texts and "₹3,00,000" in texts and "New Rule 5.2a" in texts and "Removed Rule 5.6" in texts
    assert policy["clubbing"]["creation_window_days"] == 14  # base untouched


@needs_kit
def test_amendment_changes_decisions_without_code(ds, sample_lines, policy):
    """A v5.1 effective 10 Nov raising the spot limit to 3 lakh and adding a CHK1-only rule."""
    new, _ = pol.apply_operations(policy, [
        {"op": "set_meta", "version": "5.1", "effective_from": "2026-11-10"},
        {"op": "update_rule", "rule_id": "5.4", "rule": {"when": {"all": [{"fact": "value", "op": "lt", "value": 300000},
                                                                           {"fact": "days_since_active_purchase", "op": "lte", "value": 365}]}}},
        {"op": "add_rule", "before": "5.3", "rule": {"id": "5.2b", "name": "CHK1 capex-free electricals need RFQ",
                                                     "when": {"all": [{"fact": "plant", "op": "eq", "value": "CHK1"}, {"fact": "category", "op": "eq", "value": "Electrical Spares"}]},
                                                     "then": {"decision": "SOURCING_REQUEST", "route": "RFQ", "supplier": {"mode": "suggest", "count": 3}}}},
    ])
    versions = [PolicyVersionRef("5.0", date(2026, 4, 1), policy), PolicyVersionRef("5.1", date(2026, 11, 10), new)]
    before = {(r["pr_no"], r["pr_line"]): r for r in run_batch(ds, sample_lines, versions[:1]).rows}
    after = {(r["pr_no"], r["pr_line"]): r for r in run_batch(ds, sample_lines, versions).rows}
    changed = [k for k in after if after[k]["route"] != before[k]["route"]]
    assert changed, "amendment should change some decisions"
    for k in changed:
        assert after[k]["policy_version"] == "5.1"
    # Requirements dated before 10 Nov keep v5.0
    assert after[("PR-26-00146", 1)]["policy_version"] == "5.0" and after[("PR-26-00146", 1)]["route"] == "SPOT_PO"
    # CHK1 electrical spares now go to RFQ under the plant-only rule
    chk_elec = [k for k in after if after[k]["policy_version"] == "5.1" and after[k]["resolved_item_code"] in {i for i, it in ds.items.items() if it.category == "Electrical Spares"}
                and "§5.2b" in after[k]["reason"]]
    assert chk_elec and all(after[k]["route"] == "RFQ" for k in chk_elec)


@needs_kit
def test_latest_mode_applies_newest_version_to_all(ds, sample_lines, policy):
    new = copy.deepcopy(policy)
    new["version"] = "9.9"
    rows = run_batch(ds, sample_lines, [PolicyVersionRef("5.0", date(2026, 4, 1), policy), PolicyVersionRef("9.9", date(2030, 1, 1), new)], mode="latest").rows
    assert {r["policy_version"] for r in rows} == {"9.9"}
