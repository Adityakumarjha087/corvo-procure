"""The 14 worked decisions and 3 preferred-supplier lists from Worked_Examples.pdf."""
from datetime import date

import pytest

from app.engine.pipeline import run_batch
from app.engine.suppliers import preferred_list

from .conftest import needs_kit

pytestmark = needs_kit


@pytest.fixture(scope="module")
def result(ds, sample_lines, v5):
    return run_batch(ds, sample_lines, v5)


@pytest.fixture(scope="module")
def rows(result):
    return {(r["pr_no"], r["pr_line"]): r for r in result.rows}


EXAMPLES = [
    # pr_no, route, supplier, unit price (rounded), group value (rounded), suggestions
    ("PR-26-00019", "CONTRACT_PO", "S001", 9169, 137531, ""),          # 1 contract PO
    ("PR-26-00045", "CONTRACT_PO", "S021", 2439, 26829, ""),           # 2 PDF-only contract
    ("PR-26-00004", "RFQ", "", None, 220256, "S014;S013;S016"),        # 3 ceiling nearly used up
    ("PR-26-00034", "CONTRACT_PO", "S007", 7, 32547, ""),              # 4 two contracts
    ("PR-26-00146", "SPOT_PO", "S024", 166, 126472, ""),               # 5 split PRs clubbed
    ("PR-26-00106", "SPOT_PO", "S027", 22, 156170, ""),                # 6 same item, other plant
    ("PR-26-00088", "SPOT_PO", "S023", 392, 97955, ""),                # 7 free-text match
    ("PR-26-00059", "EMERGENCY_PO", "S014", 106, 253184, ""),          # 8 emergency
    ("PR-26-00089", "RFQ", "", None, 336562, "S043;S044;S042"),        # 9 RFQ above PO limit
    ("PR-26-00050", "RFQ", "", None, 80300, "S003;S002;S005"),         # 10 small but never bought
    ("PR-26-00100", "RFP", "", None, 2070780, "S020;S017;S019;S018"),  # 11 RFP
    ("PR-26-00047", "CAPEX_SOURCING", "", None, 6036704, "S045;S047;S020;S048;S046"),  # 12 capex
    ("PR-26-00170", "NEW_ITEM_SOURCING", "", None, 141100, ""),        # 13 new item
    ("PR-26-00031", "CONTRACT_PO", "S007", 7, 23227, ""),              # 14 several requirements on one PO
]


@pytest.mark.parametrize("pr,route,sup,price,value,sugg", EXAMPLES)
def test_worked_decision(rows, pr, route, sup, price, value, sugg):
    r = rows[(pr, 1)]
    assert r["route"] == route
    assert r["supplier_id"] == sup
    if price is not None:
        assert round(float(r["unit_price"])) == price
    assert round(float(r["group_value_inr"])) == value
    assert r["suggested_supplier_ids"] == sugg
    assert r["policy_version"] == "5.0"


def test_clubbing_groups(rows):
    # 3: free-text line clubbed with the coded line
    assert rows[("PR-26-00004", 1)]["group_id"] == rows[("PR-26-00026", 1)]["group_id"]
    # 5: three PRs, one requirement
    assert len({rows[(p, 1)]["group_id"] for p in ("PR-26-00146", "PR-26-00144", "PR-26-00145")}) == 1
    # 6: same item, different plants -> separate requirements
    assert rows[("PR-26-00106", 1)]["group_id"] != rows[("PR-26-00103", 1)]["group_id"]
    # 4/14: two requirements of hex bolts
    a = rows[("PR-26-00034", 1)]["group_id"]
    b = rows[("PR-26-00031", 1)]["group_id"]
    assert a == rows[("PR-26-00032", 1)]["group_id"] and b == rows[("PR-26-00035", 1)]["group_id"] and a != b


def test_po_consolidation(rows):
    # 14: both hex-bolt requirements on the same PO
    ids = {rows[(p, 1)]["po_id"] for p in ("PR-26-00034", "PR-26-00032", "PR-26-00031", "PR-26-00035")}
    assert len(ids) == 1 and ids != {""}
    # sourcing requests never get a PO number
    assert rows[("PR-26-00089", 1)]["po_id"] == ""


def test_po_numbering_order_matches_examples(rows):
    """Examples number POs by creation time: oil (09:40) < VCI (12:00) < hex bolts (14:05) < MS sheet < hose < seal."""
    order = ["PR-26-00146", "PR-26-00106", "PR-26-00034", "PR-26-00019", "PR-26-00088", "PR-26-00059", "PR-26-00045"]
    nums = [int(rows[(p, 1)]["po_id"].split("-")[1]) for p in order]
    assert nums == sorted(nums)
    # Gaps between example PO numbers match the kit's answers exactly (only the absolute offset can differ).
    assert [n - nums[0] for n in nums] == [0, 1, 2, 10, 22, 23, 71]


def test_not_processed(rows):
    assert rows[("PR-26-00172", 1)]["route"] == "NOT_PROCESSED"  # quantity 0
    assert rows[("PR-26-00173", 1)]["route"] == "NOT_PROCESSED"  # plant PUN2


def test_no_blocked_or_inactive_supplier_used(result, ds):
    for r in result.rows:
        ids = [r["supplier_id"]] if r["supplier_id"] else []
        ids += [s for s in r["suggested_supplier_ids"].split(";") if s]
        for sid in ids:
            assert ds.suppliers[sid].status == "Active", (r["pr_no"], sid)


def test_pdf_contract_not_used_before_start(rows):
    # Laptop requirement starts 16 Nov; RC-2026-033 only from 20 Nov, so no contract PO.
    assert rows[("PR-26-00038", 1)]["route"] != "CONTRACT_PO"
    # Pneumatic cylinder on 20 Nov at CHK1 uses RC-2026-031 (PDF only).
    assert rows[("PR-26-00040", 1)]["route"] == "CONTRACT_PO" and rows[("PR-26-00040", 1)]["supplier_id"] == "S021"


@pytest.mark.parametrize("item,expected", [
    ("ITM-1048", ["S029", "S030"]),
    ("ITM-1036", ["S023", "S022", "S024"]),
    ("ITM-1016", ["S009", "S010"]),
])
def test_preferred_lists(ds, policy, item, expected):
    ranked = preferred_list(ds, item, date(2026, 11, 1), policy)
    assert [r.supplier_id for r in ranked] == expected
    assert "S031" not in [r.supplier_id for r in ranked]


def test_deterministic(ds, sample_lines, v5):
    assert run_batch(ds, sample_lines, v5).rows == run_batch(ds, sample_lines, v5).rows
