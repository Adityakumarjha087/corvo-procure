# DECISIONS.md

Where the policy (v5.0), the brief or the data is silent or ambiguous, this is what I noticed, what the app does, and why.
Each decision that a future policy might reasonably change is a **parameter in the policy JSON**, not code, and is marked ⚙️ with its path.

Every decision below is covered by tests in `backend/tests/`, including all 14 worked examples and the 3 preferred-supplier lists.

---

## A. Which policy version decides a line

**Noticed.** The brief says an approved amendment applies "from its effective date", and the blind test re-runs the same batch after approval. The policy dates contract validity and history checks by the *requirement date* (2.3).

**Decided.** Every requirement is decided by the approved version **in force on its requirement date** (the creation date of its first line). Lines dated before an amendment's effective date keep the older version, and the export's `policy_version` column says which version decided each line. If two approved versions share an effective date, the later approval wins.
A batch can also be run in **"latest version for all lines"** mode (an explicit choice when uploading) for "what if" comparisons. That mode is never the default.

**Why.** This is what "activates from its effective date" means. Silently applying a future-dated rule to past requirements would rewrite history. The impact preview in Policy Studio warns when a draft would not touch any line in the batch because of its date.

## B. Item matching (policy 1)

| Situation | Decision | Why |
|---|---|---|
| Item code given and in the master | Use it, even if the description differs | 1.1: "If the requester gave an item code, use it." |
| Item code given but **not** in the master | Fall back to matching the description, and note this in the reason | A typo in the code shouldn't turn a known item into a "new item" |
| Free text | Deterministic matcher: spec tokens (6308, M10x40, 1/2, E6013) must agree; shop-floor short forms are expanded (brg→bearing, hyd→hydraulic, pneu→pneumatic, rod→electrode, `"`→inch); noise is ignored ("- urgent", "as per sample", "(repeat)", "for maintenance") | Resolves all 39 free-text lines in the sample correctly and never confuses 6205 with 6308 |
| Two items fit the description equally well (e.g. "ball bearing") | **Batch:** `NOT_PROCESSED` with both candidates named. **Chat:** the assistant asks which one | Guessing would buy the wrong part, and the brief says "avoid inventing items" |
| Nothing scores above the threshold ⚙️ `item_matching.min_score` (0.72) | New item → `NEW_ITEM_SOURCING` | 1.2 |
| New item without an estimated price | Still `NEW_ITEM_SOURCING`, value left blank, reason says the buyer must estimate it. The chat assistant always asks for an estimate | 1.2 values new items at the requester's estimate. With no estimate, an invented number would be worse than an honest blank |

## C. Clubbing (policy 2)

- **The need-by window is measured against the requirement's first line**, not the previous line (no chaining). This is the literal 2.2 wording, and it is the only reading that reproduces worked examples 4 and 14 (PR-34+PR-32 and PR-31+PR-35 form two requirements).
- **"Within 14 calendar days"** is a calendar-date difference (first line on 2 Nov → lines up to 16 Nov join), not 336 hours. ⚙️ `clubbing.creation_window_days`, `clubbing.need_by_window_days`
- **Order** is creation time, then PR number, then line number, whatever the order of rows in the file (the sample file is not sorted).
- **Department and requester are ignored.** Splitting across departments is exactly the abuse 2.1 targets. ⚙️ `clubbing.same` can add `department` or `requester` if Procurement ever wants that.
- **Capex lines are clubbed too.** 5.1 decides the route, but 2.1's "apply every limit to the total" still makes sense for capex value.
- **Lines with no need-by date** cannot satisfy the ±7-day test, so they are never clubbed and form their own requirement.
- **Multi-line PRs** (e.g. PR-164 to PR-169, whose lines go to different plants and departments) are handled line by line. A PR number is not a requirement.

**Possible duplicate: PR-26-00174 and PR-26-00175.** These are the same requester, same item (servo drive), same quantity and same need-by, four minutes apart, with different departments and estimates. 2.1 says to treat such lines as one requirement, so they are clubbed (qty 2 → spot PO). I did not delete either line: I can't prove it's a duplicate, and a wrong deletion would leave a real need unbought. The buyer sees both lines on one requirement and can override. *Side effect:* this requirement is the earliest PO of the batch (08:10), so my PO numbers run one higher than those in the worked examples (PO-0012 vs PO-0011). The groupings and the gaps between example PO numbers match exactly (test `test_po_numbering_order_matches_examples`). `po_id` is defined as "your PO number".

## D. Valuation (policy 3)

- **3.1(b) uses the most recent PO from any supplier**, including Blocked or Inactive ones. That is the literal text. Worked example 6 confirms that the valuation price and the PO price can differ: the VCI bag is valued at S028's 21.19 but ordered from S027 at 21.59. A blocked supplier's last price is still the best evidence of market price. It only must not *receive* the order (5.7), and it never does. This affects ITM-1014, 1017, 1020, 1049 and 1050. ⚙️ `valuation.last_po_active_suppliers_only` flips it.
- **Ties** (two POs for an item on the same date): the higher PO number counts as more recent.
- **Look-back windows are inclusive**: a PO exactly 365 days before the requirement date counts. ⚙️ `valuation.last_po_lookback_days`
- **Rounding**: values and prices are kept unrounded for comparisons and written with 2 decimals in the export. Policy limits compare the exact value.

## E. Contracts and ceilings (policy 4)

- **Applicable** = covers the item, requirement date within start–end inclusive, supplier Active. RC-2026-005 (S004, Blocked) is therefore never used. RC-2025-020 (expired 30 Sep) is not applicable, but S033 still counts as a contract holder in the preferred list (6.1b says "even if it has since expired").
- **PDF-only contracts** (RC-2026-031 from 15 Nov, RC-2026-033 from 20 Nov) are read from the PDFs on load, start at zero consumption (4.2) and are binding from their start date (4.4). PR-38 (laptops, 16 Nov) and PR-44 (20 Nov) club into one requirement dated 16 Nov, *before* RC-2026-033 starts, so neither uses the contract. That is the consequence of 2.3, and the reason says so.
- **Ceiling consumption** happens only when a requirement actually becomes a `CONTRACT_PO`, in requirement-date order (4.2). A capex requirement that happens to be on contract does not consume ceiling.
- **Each batch run starts from the register's consumed values.** Re-running the same batch, as in Run 2, gives reproducible results, and runs don't consume each other's ceiling. In a live deployment, approving a PO would post consumption back to the register; that sync is out of scope here.
- **Several usable contracts**: lowest rate wins (4.3). On an exact rate tie, the one with more ceiling left wins, then the contract id.

## F. Decision rules (policy 5)

- **Boundaries are exactly as written**: emergency **≤** ₹5,00,000; spot **<** ₹2,00,000; RFQ **<** ₹10,00,000; RFP **≥** ₹10,00,000. They are stored as `lte`/`lt`/`gte` conditions, so an amendment can change any of them.
- **"Bought from an Active supplier in the last 365 days"** looks at any plant: history is per item, not per plant. It counts a PO on the requirement date itself. Implemented as the fact `days_since_active_purchase ≤ 365`, so an amendment can change the window per rule.
- **Emergency** = the urgency field. Free text like "- urgent" in a description (8 lines in the sample) does **not** create an emergency: the field is what the requester formally declared, and treating words as emergencies would open the 5L no-quote route to anyone who types "urgent". The chat assistant asks the requester to confirm when they sound urgent.
- **The PO supplier for 5.3/5.4** is the 1st preferred supplier (548-day list) at its reference price, as written, even if a different supplier made the 365-day purchase. If no preferred supplier has a reference price, the requirement goes to RFQ instead and the reason says why. Never a PO without a priced, eligible supplier.
- **No rule matches** (possible only after an amendment): fallback to RFQ with 3 suggestions. ⚙️ `fallback`
- **Invalid lines** → `NOT_PROCESSED` with a reason that tells the requester what to fix:
  - unknown plant (PR-173 `PUN2`)
  - quantity ≤ 0 (PR-172)
  - a duplicate `pr_no/pr_line`
  - a missing or unreadable timestamp
  - an ambiguous description (B)

## G. Preferred suppliers (policy 6): ranking method

**Who is on the list (6.1).** Active suppliers with a PO for the item in the 548 days up to the date, or a contract for the item that started on or before the date (even if it has since expired). Contracts starting after the date don't count yet: S021 is not on ITM-1036's list on 1 Nov, because RC-2026-031 starts 15 Nov.

**Score (6.2)**, weights stored in the policy ⚙️ `preferred_suppliers.weights`:

| Component | Weight | Definition |
|---|---|---|
| Frequency | 0.30 | supplier's POs for the item in the window ÷ the most any listed supplier has |
| Recency | 0.30 | 1.0 if the last PO is within 90 days, 0.5 within 365 days, else 0 (the bands in the worked examples) |
| Contract | 0.15 | 1 if it has held a contract for the item |
| Performance | 0.25 | mean of on-time % and quality ÷ 5, from the supplier master |

Ties go to the more recent last PO, then supplier id.

**Why these weights.** The ranking is for "the best choice for a direct PO". Proven, recent supply matters most, a contract shows a negotiated relationship, and ratings separate otherwise similar suppliers. I fitted and checked the method against every ranking the kit implies, not only the three published lists:

- **ITM-1048:** S029 > S030 (S031 Inactive excluded).
- **ITM-1036:** S023 > S022 > S024. Recency beats S024's better ratings.
- **ITM-1016:** S009 > S010. The contract breaks the tie.
- **Hydraulic oil (example 5):** S024 is chosen over S023, which has more POs. Recency outweighs frequency.
- **VCI bag (example 6):** S027 over S028, with equal history. Performance decides.
- **Bearings 6308 (example 3):** S014, S013, S016. The contract lifts S013 above S016.
- **CMM calibration (example 9):** S043, S044.

**On-time %** comes from the supplier master, not recomputed from `delivered_on_time` in PO history. The worked examples quote the master figures, and the master covers suppliers with few POs.

**Reference price (6.3)** is the supplier's most recent PO price in 548 days, or else its most recent contract rate.

**Buyers see why.** Every ranking shows each component as a stacked bar with the raw facts: POs, last PO date, contract, on-time, quality and reference price. This appears both in the decision drawer and on the Preferred Suppliers page.

**Export** gives the top 3 per item as of any date. Items with nobody on the list (e.g. ITM-1006, whose only contract holder is Blocked) produce no rows: 6.1 defines the list, and category top-up applies only to sourcing suggestions.

**Sourcing suggestions (6.4)** take the list in order, then top up with Active suppliers of the item's category, ranked by the performance score. This order reproduces examples 3, 9, 10, 11 and 12 exactly. **If there aren't enough eligible suppliers, fewer are suggested** (example 11 shows 4 for an RFP). Padding with ineligible or off-category suppliers would be worse. New items get none (6.4).

## H. PO consolidation (policy 7)

- Requirements share a PO when **supplier, plant and route** are the same, and the requirement's first line was created **within 24 hours after the first requirement on that PO** (not a rolling window). ⚙️ `consolidation.window_hours`, `consolidation.same`
- A contract PO and a spot PO to the same supplier stay separate (different route), as 7.1 says.
- Emergency POs consolidate like any other PO route.
- PO numbers are assigned in creation order of each PO's first requirement.

## I. Policy as data: how amendments are handled

- The policy is a JSON document containing:
  - parameters (all windows, limits and weights)
  - an **ordered list of rules**, each with a condition tree over named facts and an outcome (decision, route, supplier mode)
  - a fallback

  New kinds of rule are expressed in data: plant-only rules, category-specific limits, department rules, supplier-performance floors, new route names, reordering, disabling a rule.
- **Amendment intake:** a PDF/TXT upload or a plain-language request goes to Claude, which returns *edit operations* (set parameter, add/update/remove/move rule), never a whole new policy. The server applies the operations to the latest approved version, validates the result (unknown facts, operators, outcomes and malformed values are rejected), and computes a **deterministic plain-language diff**. The approver sees the diff, the AI's summary, any points the AI flagged as uncertain, and an **impact preview** listing every decision in the latest batch that would change. Only then can it be approved.
- If the document gives no effective date, the draft defaults to today and is flagged for the approver to confirm. The draft's version number defaults to the base +0.1 if none is stated.
- Approved versions are immutable. Drafts can be edited (effective date, version, or the full JSON) before approval. Every step is in the audit log.
- Without an AI key, the same flow works through the **Rule builder** (forms for every limit and rule: conditions, order, enable/disable, outcome) or "Edit as JSON". The validation, diff, impact preview and approval are identical.

## J. Buyer actions and records (policy 8)

- **Approve** creates the document: a PO for a consolidated PO; an RFQ, RFP, capex or new-item sourcing event for a sourcing requirement.
- **Override** requires a written reason of at least 5 characters, refuses Blocked or Inactive suppliers (5.7), and keeps the original decision next to the override.
- The export defaults to **engine decisions**, which is what the blind test scores. "CSV incl. overrides" exports the buyer's final position.
- Identity is lightweight: the user picks who they are acting as (top right). The name is sent with every request and stored in the audit log. Real authentication is out of scope for this exercise and would replace the header.

## K. Data and dates

- Timestamps are treated as IST wall-clock time, with no timezone conversion.
- The item master's unit of measure is authoritative. The chat assistant tells the requester when they used a different unit.
- PO history is as at 28 Oct 2026. Decisions made by the app don't feed back into "history" for later requirements in the same batch, which keeps runs reproducible and order-independent beyond what the policy defines.
- Chat dates: "Friday" and "next Friday" both mean the coming Friday, never today. The resolved date is always shown back before the PR is raised.
- The task kit is not committed (rule from Cantill). It is loaded at runtime from `KIT_DIR` or uploaded in **Data & audit**. PDFs of contracts not in the register are added automatically. PDFs already in the register are cross-checked: all 10 match.
