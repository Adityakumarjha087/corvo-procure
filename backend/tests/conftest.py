import glob
import json
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.engine.loaders import dataset_from_dir, pr_lines_from_csv  # noqa: E402
from app.engine.model import Contract, ContractLine, PolicyVersionRef  # noqa: E402
from app.ingest.contract_pdf import extract_contract_pdf  # noqa: E402

# The task kit is not committed (task rule). Point KIT_DIR at it to run the data-driven tests.
KIT_DIR = os.getenv("KIT_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "data", "kit"))
HAS_KIT = os.path.isfile(os.path.join(KIT_DIR, "master_data", "item_master.csv"))
needs_kit = pytest.mark.skipif(not HAS_KIT, reason="task kit not available (set KIT_DIR)")


@pytest.fixture(scope="session")
def policy():
    with open(os.path.join(os.path.dirname(__file__), "..", "app", "policy", "corvo_v5_0.json")) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def ds():
    base = dataset_from_dir(KIT_DIR)
    extra = {}
    for f in glob.glob(os.path.join(KIT_DIR, "contracts", "pdf", "*.pdf")):
        c = extract_contract_pdf(open(f, "rb").read())
        if c["contract_id"] not in base.contracts:
            extra[c["contract_id"]] = Contract(c["contract_id"], c["supplier_id"], c["supplier_name"], c["start_date"], c["end_date"],
                                               c["value_cap"], 0.0, {l["item_code"]: ContractLine(l["item_code"], l["rate"]) for l in c["lines"]}, "pdf")
    return dataset_from_dir(KIT_DIR, extra)


@pytest.fixture(scope="session")
def sample_lines():
    return pr_lines_from_csv(open(os.path.join(KIT_DIR, "pr_batches", "sample_pr_batch.csv")).read())


@pytest.fixture(scope="session")
def v5(policy):
    return [PolicyVersionRef("5.0", date(2026, 4, 1), policy)]
