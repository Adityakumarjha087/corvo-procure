"""Read a policy amendment (PDF or text) and turn it into edit operations on the current policy JSON.

The model never writes the policy directly: it proposes operations, the server applies and validates
them, and the buyer sees a deterministic plain-language diff before approving.
"""
from __future__ import annotations

import base64
import json

from ..engine.rules import FACTS, OPS
from ..policy.service import PARAM_LABELS, SUPPLIER_MODES
from .client import structured

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["version", "effective_from", "title", "summary", "operations", "uncertainties"],
    "properties": {
        "version": {"type": ["string", "null"], "description": "New version number stated in the document, else null"},
        "effective_from": {"type": ["string", "null"], "description": "Effective date YYYY-MM-DD stated in the document, else null"},
        "title": {"type": ["string", "null"]},
        "summary": {"type": "string", "description": "2-4 sentence plain-language summary of what the amendment changes"},
        "operations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["op", "path", "value_json", "rule_id", "rule_json", "before", "after", "explanation"],
                "properties": {
                    "op": {"type": "string", "enum": ["set_param", "add_rule", "update_rule", "remove_rule", "move_rule"]},
                    "path": {"type": ["string", "null"], "description": "Dotted parameter path for set_param"},
                    "value_json": {"type": ["string", "null"], "description": "JSON-encoded new value for set_param"},
                    "rule_id": {"type": ["string", "null"], "description": "Target rule id for update/remove/move"},
                    "rule_json": {"type": ["string", "null"], "description": "JSON-encoded full rule object for add_rule/update_rule"},
                    "before": {"type": ["string", "null"], "description": "Place the rule before this rule id"},
                    "after": {"type": ["string", "null"], "description": "Place the rule after this rule id"},
                    "explanation": {"type": "string", "description": "Which clause of the amendment this implements"},
                },
            },
        },
        "uncertainties": {"type": "array", "items": {"type": "string"}, "description": "Anything ambiguous the approver should check"},
    },
}

SYSTEM = """You convert procurement policy amendments into precise edit operations on a machine-readable policy.

The decision engine walks `rules` in order; the first rule whose `when` condition matches decides the outcome.
A condition is {"fact": <fact>, "op": <op>, "value": <value>} or a group {"all": [...]}, {"any": [...]}, {"not": {...}}.
A rule is {"id": str, "name": str, "when": <condition>, "then": {"decision": "PO"|"SOURCING_REQUEST"|"NOT_PROCESSED",
"route": str, "supplier": {"mode": "contract"|"preferred"|"suggest"|"none"|"fixed", "rank"?: int, "count"?: int,
"pick"?: "lowest_price", "among"?: int, "supplier_id"?: str}, "note"?: str}}.
- PO rules need supplier mode "contract" (contract supplier at contract rate), "preferred" (preferred supplier #rank at its
  reference price; or pick "lowest_price" among the top N) or "fixed".
- Sourcing rules use mode "suggest" with a count of suppliers to suggest, or "none".
- Known routes: CONTRACT_PO, EMERGENCY_PO, SPOT_PO, RFQ, RFP, CAPEX_SOURCING, NEW_ITEM_SOURCING, NOT_PROCESSED. Use a new
  route name only if the amendment explicitly creates one.

Facts available to conditions:
{facts}
Operators: {ops}
Tunable parameters (use set_param with these dotted paths; value_json is the JSON-encoded value):
{params}
Other parameter paths in the current policy JSON are also valid if the amendment clearly targets them.

How to work:
- Change only what the amendment changes. Keep every other rule and parameter as it is.
- Money is INR: 1 lakh = 100000, 1 crore = 10000000. "below"/"less than" = lt, "up to"/"not more than"/"at most" = lte,
  "above"/"more than" = gt, "or more"/"at least" = gte. Keep the existing boundary style unless the text changes it.
- "Bought in the last N days from an Active supplier" is {"fact": "days_since_active_purchase", "op": "lte", "value": N}.
- To change a limit in an existing rule, use update_rule with the complete updated rule in rule_json.
- New rules: choose an id that fits the clause numbering (e.g. "5.2a") and place them with before/after so they are
  checked at the right point. Plant-only or category-only rules are ordinary rules with plant / category conditions.
- Placement is critical because the FIRST matching rule wins. Before choosing a position, check every existing rule
  above it: if an earlier rule would also match some of the new rule's cases and give a different outcome, the new rule
  never fires for them. So a narrower rule that overrides the general ladder (a plant-, category- or department-specific
  limit or route) goes BEFORE the general rules it overrides (e.g. a sourcing rule for some items above a value goes before
  "5.4 Spot PO" and "5.3 Emergency PO", otherwise those still catch the lower values). If the text says "always",
  "regardless" or "even if on contract", place it before the contract rule 5.2 (but after 5.1 capex unless told otherwise).
  If the text gives an explicit position, follow it. Mention the placement reasoning in the operation's explanation.
- Do NOT add requirement_date conditions for the effective date; versions already apply from effective_from.
- For sourcing rules, suggest 3 suppliers unless the text states a number.
- Use category values exactly as written in the item master (e.g. "Safety & PPE", "Office & IT") and plant codes
  (e.g. CHK1, PUN1) rather than plant names.
- If the amendment restates the whole policy, still express it as the minimal set of operations.
- version: the new version number if stated (e.g. "5.1"). effective_from: the stated effective date as YYYY-MM-DD; if only a
  month/day is given, use the year of the document. Null if not stated.
- List genuinely ambiguous points in uncertainties instead of guessing silently.

Supplier modes allowed: {modes}."""


def _system() -> str:
    # Plain replacement, not str.format: the prompt contains literal JSON braces.
    values = {
        "facts": "\n".join(f"- {k}: {v}" for k, v in FACTS.items()),
        "ops": ", ".join(OPS),
        "params": "\n".join(f"- {k}: {v[0]}" for k, v in PARAM_LABELS.items()),
        "modes": ", ".join(sorted(SUPPLIER_MODES)),
    }
    out = SYSTEM
    for k, v in values.items():
        out = out.replace("{" + k + "}", v)
    return out


def read_amendment(current: dict, text: str | None = None, pdf_bytes: bytes | None = None, source_name: str = "") -> dict:
    content: list[dict] = []
    if pdf_bytes:
        content.append({"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                         "data": base64.standard_b64encode(pdf_bytes).decode()}})
    intro = (f"Current policy (version {current.get('version')}, effective {current.get('effective_from')}):\n"
             f"```json\n{json.dumps(current, indent=1)}\n```\n\n")
    if text:
        intro += f"Amendment or requested change ({source_name or 'text'}):\n<amendment>\n{text}\n</amendment>\n"
    else:
        intro += f"The amendment is the attached document ({source_name}).\n"
    intro += "Return the edit operations that implement it."
    content.append({"type": "text", "text": intro})
    out = structured(_system(), content, SCHEMA, effort="high", max_tokens=16000)
    ops = []
    for o in out.get("operations", []):
        op = {"op": o["op"], "explanation": o.get("explanation", "")}
        if o.get("path"):
            op["path"] = o["path"]
        if o.get("value_json") is not None:
            try:
                op["value"] = json.loads(o["value_json"])
            except json.JSONDecodeError:
                op["value"] = o["value_json"]
        if o.get("rule_id"):
            op["rule_id"] = o["rule_id"]
        if o.get("rule_json"):
            try:
                op["rule"] = json.loads(o["rule_json"])
            except json.JSONDecodeError:
                op["explanation"] += " (rule JSON could not be parsed)"
        for k in ("before", "after"):
            if o.get(k):
                op[k] = o[k]
        ops.append(op)
    out["operations"] = ops
    return out
