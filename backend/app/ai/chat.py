"""Chat intake: turn a conversation into confirmed PR lines.

Claude (when configured) only extracts fields from what the requester typed. Item matching, follow-up
questions, validation and the decision preview are deterministic, so the assistant never invents an item.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from dateutil import parser as dparser
from dateutil.relativedelta import relativedelta

from ..engine.matcher import ItemMatcher, normalise
from . import client as ai

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
UOM_WORDS = {
    "nos": "NOS", "no": "NOS", "pcs": "NOS", "pc": "NOS", "pieces": "NOS", "piece": "NOS", "units": "NOS", "unit": "NOS", "numbers": "NOS",
    "kg": "KG", "kgs": "KG", "kilo": "KG", "kilos": "KG", "ltr": "LTR", "l": "LTR", "litre": "LTR", "litres": "LTR", "liters": "LTR",
    "mtr": "MTR", "m": "MTR", "meter": "MTR", "meters": "MTR", "metre": "MTR", "metres": "MTR", "pair": "PAIR", "pairs": "PAIR",
    "roll": "ROL", "rolls": "ROL", "set": "SET", "sets": "SET", "ream": "REAM", "reams": "REAM", "cyl": "CYL", "cylinders": "CYL",
    "bucket": "BKT", "buckets": "BKT", "bkt": "BKT", "barrel": "BRL", "barrels": "BRL", "brl": "BRL", "job": "JOB", "jobs": "JOB",
    "month": "MON", "months": "MON",
}

EXTRACT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["items", "plant", "need_by_date", "urgency", "urgency_hint", "selection", "confirm", "cancel", "department"],
    "properties": {
        "items": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["description", "item_code", "quantity", "uom", "estimated_unit_price"],
            "properties": {
                "description": {"type": ["string", "null"], "description": "What the person wants, in their words, without quantity/plant/date"},
                "item_code": {"type": ["string", "null"], "description": "Only if the user literally typed an item code like ITM-1048"},
                "quantity": {"type": ["number", "null"]},
                "uom": {"type": ["string", "null"]},
                "estimated_unit_price": {"type": ["number", "null"], "description": "Price per unit in INR if the user gave one"},
            }}},
        "plant": {"type": ["string", "null"], "description": "Plant code from the list, or null"},
        "need_by_date": {"type": ["string", "null"], "description": "YYYY-MM-DD resolved against today's date, or null"},
        "urgency": {"type": ["string", "null"], "enum": ["Emergency", "Normal", None]},
        "urgency_hint": {"type": "boolean", "description": "User sounds urgent (urgent, asap, breakdown) without explicitly asking for an emergency PR"},
        "selection": {"type": ["string", "null"], "description": "If the user is choosing among offered items: the item code, or NEW for 'none of these / new item'"},
        "confirm": {"type": "boolean", "description": "User confirms the summary (yes, confirm, go ahead)"},
        "cancel": {"type": "boolean", "description": "User wants to cancel or start over"},
        "department": {"type": ["string", "null"]},
    },
}

EXTRACT_SYSTEM = """You extract purchase-request fields from a factory employee's chat message for Corvo Engineering.
Only report what the user actually said in THIS message; use null for anything not mentioned. Never invent an item,
quantity, plant or date. Resolve relative dates ("next Friday", "in 10 days", "end of month") against today's date.
Plants: {plants}. Map plant names (e.g. Chakan, Bhosari) to their codes.
If the assistant asked a question, interpret a short answer in that context (e.g. "300" answers a quantity question,
"2" or "the second one" picks the second offered item, "Chakan" answers the plant question)."""


# ---------------------------------------------------------------- deterministic extraction
def _parse_date(text: str, today: date) -> date | None:
    t = text.lower()
    if "day after tomorrow" in t:
        return today + timedelta(days=2)
    if "tomorrow" in t:
        return today + timedelta(days=1)
    if re.search(r"\btoday\b|\basap\b|\bimmediately\b", t):
        return today
    m = re.search(r"in\s+(\d+)\s+(day|days|week|weeks)", t)
    if m:
        n = int(m.group(1))
        return today + timedelta(days=n * (7 if m.group(2).startswith("week") else 1))
    if "end of month" in t or "month end" in t:
        return (today.replace(day=1) + relativedelta(months=1)) - timedelta(days=1)
    if "next week" in t:
        return today + timedelta(days=7)
    m = re.search(r"(next|this|coming|by)?\s*(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", t)
    if m:
        # "Friday", "by Friday", "next Friday" all mean the coming Friday (never today); the resolved date is
        # always shown back to the requester before the PR is raised, so a different reading is easy to correct.
        wd = WEEKDAYS.index(m.group(2))
        delta = (wd - today.weekday()) % 7 or 7
        return today + timedelta(days=delta)
    m = re.search(r"(\d{4}-\d{2}-\d{2})", t)
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*(?:\s+\d{4})?|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?|\d{1,2}[/.]\d{1,2}(?:[/.]\d{2,4})?)\b", t)
    if m:
        try:
            d = dparser.parse(re.sub(r"(st|nd|rd|th)\b", "", m.group(1)), dayfirst=True, default=datetime(today.year, today.month, today.day)).date()
            if d < today and not re.search(r"\d{4}", m.group(1)):
                d = d.replace(year=d.year + 1)
            return d
        except (ValueError, OverflowError):
            return None
    return None


def _strip_date_phrases(t: str) -> str:
    pats = [r"\b(by|before|on|for|till|until)?\s*(next|this|coming)?\s*(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
            r"\b(by|before|on|till|until)?\s*(tomorrow|today|day after tomorrow|next week|end of (the )?month|month end)\b",
            r"\bin\s+\d+\s+(days?|weeks?)\b", r"\b(by|before|on|till|until)?\s*\d{4}-\d{2}-\d{2}\b",
            r"\b(by|before|on|till|until)?\s*\d{1,2}(st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*(\s+\d{4})?\b",
            r"\b(by|before|on|till|until)?\s*\d{1,2}[/.]\d{1,2}([/.]\d{2,4})?\b"]
    for p in pats:
        t = re.sub(p, " ", t, flags=re.I)
    return t


def regex_extract(message: str, plants: dict[str, str], today: date, awaiting: str | None, n_candidates: int) -> dict:
    t = message.strip()
    low = t.lower()
    out = {"items": [], "plant": None, "need_by_date": None, "urgency": None, "urgency_hint": False, "selection": None,
           "confirm": False, "cancel": False, "department": None}
    if re.fullmatch(r"(yes|y|yep|ok|okay|confirm|confirmed|go ahead|create( it)?|create pr|looks good|correct|submit)[.! ]*", low):
        out["confirm"] = True
        return out
    if re.search(r"\b(cancel|start over|reset|forget it)\b", low):
        out["cancel"] = True
        return out
    m = re.search(r"\b(ITM-\d{3,6})\b", t, re.I)
    if awaiting in ("item_choice", "new_item_confirm"):
        if m and awaiting == "item_choice":
            out["selection"] = m.group(1).upper()
            return out
        if re.search(r"\b(none|new item|not listed|neither)\b", low):
            out["selection"] = "NEW"
            return out
        mm = re.fullmatch(r"(?:option\s*)?#?\s*(\d)\s*", low)
        if mm and 1 <= int(mm.group(1)) <= n_candidates:
            out["selection"] = f"#{mm.group(1)}"
            return out
    # plant
    for code, name in plants.items():
        if re.search(rf"\b{code.lower()}\b", low):
            out["plant"] = code
    if out["plant"] is None:
        if "chakan" in low or re.search(r"\bchk\b", low):
            out["plant"] = next((c for c, n in plants.items() if "chakan" in n.lower()), None)
        elif "bhosari" in low or re.search(r"\bpune\b|\bpun\b", low):
            out["plant"] = next((c for c, n in plants.items() if "bhosari" in n.lower() or "pune" in n.lower()), None)
    # urgency
    if re.search(r"\bemergency\b", low):
        out["urgency"] = "Emergency"
    elif re.search(r"\bnormal\b|\bnot urgent\b|\bregular\b", low):
        out["urgency"] = "Normal"
    elif re.search(r"\burgent|asap|breakdown|line down|immediately\b", low):
        out["urgency_hint"] = True
    out["need_by_date"] = (_parse_date(low, today) or None)
    if out["need_by_date"]:
        out["need_by_date"] = out["need_by_date"].isoformat()
    # price
    price = None
    pm = re.search(r"(?:₹|\brs\.?|\binr)\s*([\d,]+(?:\.\d+)?)|(?<![\w.])([\d,]+(?:\.\d+)?)\s+(?:rs|rupees|inr)\b|@\s*([\d,]+(?:\.\d+)?)", low)
    rest = low
    if pm:
        price = float((pm.group(1) or pm.group(2) or pm.group(3)).replace(",", ""))
        rest = rest.replace(pm.group(0), " ")
    # strip known parts to leave the item description
    rest = _strip_date_phrases(rest)
    for code, name in plants.items():
        rest = re.sub(rf"\b(for|at|to|in)?\s*{code.lower()}\b", " ", rest)
    rest = re.sub(r"\b(for|at|to|in)?\s*(the\s+)?(chakan|bhosari|pune)(\s+plant)?\b", " ", rest)
    rest = re.sub(r"\b(emergency|urgent(ly)?|asap|normal|not urgent|regular|breakdown|line down)\b", " ", rest)
    rest = re.sub(r"\b(i|we)\s+(need|want|require|would like)\b|\b(please|pls|kindly|need|want|require|order|get me|buy|send|raise a pr for|raise pr for|a pr for)\b", " ", rest)
    # quantity: first standalone number not part of a spec token
    # Quantity: a number with a unit word, else a number that opens the request ("200 nitrile gloves"),
    # else "qty 50". A bare number inside the description (bearing 6205, 24 inch) is never taken as quantity.
    qty, uom = None, None
    units = "|".join(sorted(UOM_WORDS, key=len, reverse=True))
    qm = re.search(rf"(?<![\w./-])(\d+(?:\.\d+)?)\s*({units})\b(?!\s*(?:inch|mm))", rest)
    if qm:
        qty, uom = float(qm.group(1)), UOM_WORDS[qm.group(2)]
        rest = rest[:qm.start()] + " " + rest[qm.end():]
    else:
        qm = re.match(r"\s*(?:qty\s*[:=]?\s*)?(\d+(?:\.\d+)?)\s+(?:x\s+|of\s+)?(?=[a-z])(?!inch|mm|ton|hp|kw|micron|ply|pole|core)", rest) \
            or re.search(r"\bqty\s*[:=]?\s*(\d+(?:\.\d+)?)", rest)
        if qm:
            qty = float(qm.group(1))
            rest = rest[:qm.start()] + " " + rest[qm.end():]
    if awaiting == "new_item_price" and price is None:
        nm = re.search(r"(\d[\d,]*(?:\.\d+)?)", low)
        if nm:
            price, qty = float(nm.group(1).replace(",", "")), None
    if awaiting == "quantity" and qty is None:
        nm = re.search(r"(\d+(?:\.\d+)?)", low)
        if nm:
            qty = float(nm.group(1))
    rest = re.sub(r"\b(each|per (unit|piece|pc|no))\b|[,;]", " ", rest)
    desc = re.sub(r"\s+", " ", re.sub(r"^[\s,.;:-]+|[\s,.;:-]+$", "", rest)).strip()
    desc = re.sub(r"^(of|some|a|an|the)\s+", "", desc)
    if awaiting in ("quantity", "plant", "need_by", "urgency", "urgent_confirm", "new_item_price", "confirm") and len(desc.split()) <= 2:
        desc = ""  # short answers to a question are not new item descriptions
    if desc or qty is not None or price is not None or m:
        out["items"].append({"description": desc or None, "item_code": m.group(1).upper() if m else None, "quantity": qty, "uom": uom,
                             "estimated_unit_price": price})
    return out


def ai_extract(message: str, plants: dict[str, str], today: date, state: dict) -> dict:
    ctx = (f"Today is {today.isoformat()} ({today.strftime('%A')}).\n"
           f"Assistant's last question: {state.get('last_question') or 'none'}\n")
    if state.get("candidates"):
        ctx += "Offered items: " + "; ".join(f"{i + 1}. {c['item_code']} {c['description']}" for i, c in enumerate(state["candidates"])) + "\n"
    ctx += f"User message: {message}"
    out = ai.structured(EXTRACT_SYSTEM.format(plants=", ".join(f"{k} ({v})" for k, v in plants.items())),
                        ctx, EXTRACT_SCHEMA, effort="low", max_tokens=2000)
    if out.get("selection") and re.fullmatch(r"\d", str(out["selection"])):
        out["selection"] = f"#{out['selection']}"
    return out


# ---------------------------------------------------------------- conversation
def _fmt_date(d: str | None) -> str:
    if not d:
        return "-"
    try:
        return date.fromisoformat(d).strftime("%a %d %b %Y")
    except ValueError:
        return d


class ChatEngine:
    def __init__(self, items: dict, plants: dict[str, str], today: date | None = None):
        self.items = items
        self.plants = plants
        self.matcher = ItemMatcher(items)
        self.today = today or date.today()

    def start(self) -> dict:
        return {"text": "Hi! Tell me what you need. For example: “need 200 nitrile gloves for Chakan by next Friday”. "
                        "I'll match the item, ask for anything missing, and raise the PR.",
                "quick_replies": [{"label": "200 nitrile gloves for Chakan by next Friday", "value": "need 200 nitrile gloves for Chakan by next Friday"},
                                  {"label": "Hydraulic oil for Bhosari", "value": "hydraulic oil HLP 68 for Bhosari"}]}

    def handle(self, message: str, state: dict) -> tuple[dict, dict]:
        """Return (reply, new_state). reply['ready'] is set when the draft is complete."""
        st = {**state}
        st.setdefault("draft", {})
        st.setdefault("queue", [])
        awaiting = st.get("awaiting")
        source = "regex"
        try:
            if ai.available():
                ext = ai_extract(message, self.plants, self.today, st)
                source = "ai"
            else:
                raise ai.AIError("off")
        except ai.AIError:
            ext = regex_extract(message, self.plants, self.today, awaiting, len(st.get("candidates") or []))
        st["extracted_by"] = source

        if ext.get("cancel"):
            return {"text": "Okay, I've cleared that request. What do you need?"}, {"draft": {}, "queue": []}
        d = st["draft"]

        # ---- item choice
        sel = ext.get("selection")
        if awaiting == "item_choice" and not sel and ext.get("confirm") and len(st.get("candidates") or []) == 1:
            sel = "#1"
        if awaiting in ("item_choice", "new_item_confirm") and sel:
            if sel == "NEW":
                d.update(is_new=True, item_code=None)
            else:
                code = sel
                if sel.startswith("#"):
                    i = int(sel[1:]) - 1
                    cands = st.get("candidates") or []
                    code = cands[i]["item_code"] if 0 <= i < len(cands) else None
                if code and code in self.items:
                    it = self.items[code]
                    d.update(item_code=code, item_desc=it.description, uom=it.uom, is_new=False)
            st["candidates"] = []

        # ---- merge extracted values
        items = [i for i in (ext.get("items") or []) if any(v is not None for v in i.values())]
        if items:
            first = items[0]
            new_desc = first.get("description")
            if (first.get("item_code") or (new_desc and not d.get("description"))) or (new_desc and awaiting in (None, "item_choice", "new_item_confirm") and not d.get("item_code")):
                if new_desc and (not d.get("description") or not d.get("item_code")):
                    d["description"] = new_desc
                    if not d.get("is_new"):
                        d.pop("item_code", None)
                if first.get("item_code"):
                    d["typed_code"] = first["item_code"].upper()
            if first.get("quantity") is not None:
                d["quantity"] = first["quantity"]
            if first.get("uom"):
                d["typed_uom"] = first["uom"]
            if first.get("estimated_unit_price") is not None:
                d["estimated_unit_price"] = first["estimated_unit_price"]
            for extra in items[1:]:
                if extra.get("description"):
                    st["queue"].append(extra)
        if ext.get("plant") in self.plants:
            d["plant"] = ext["plant"]
        elif ext.get("plant"):
            st["note"] = f"I don't know plant “{ext['plant']}”."
        if ext.get("need_by_date"):
            d["need_by_date"] = ext["need_by_date"]
        if ext.get("urgency") in ("Emergency", "Normal"):
            d["urgency"] = ext["urgency"]
        elif ext.get("urgency_hint") and not d.get("urgency"):
            d["urgency_hint"] = True
        if ext.get("department"):
            d["department"] = ext["department"]
        if awaiting == "urgent_confirm" and ext.get("confirm") and not d.get("urgency"):
            d["urgency"] = "Emergency"

        reply = self._next(st, confirm=bool(ext.get("confirm")))
        reply["extracted_by"] = source
        return reply, st

    # ------------------------------------------------------------------
    def _resolve_item(self, st: dict) -> dict | None:
        d = st["draft"]
        if d.get("item_code") or d.get("is_new"):
            return None
        code = d.get("typed_code")
        if code and code in self.items:
            it = self.items[code]
            d.update(item_code=code, item_desc=it.description, uom=it.uom)
            return None
        desc = d.get("description")
        if not desc:
            st["awaiting"] = "description"
            st["last_question"] = "What item do you need?"
            return {"text": ("I couldn't find item code " + code + ". " if code else "") + "What item do you need? A short description is fine (e.g. “brg 6205 2rs”)."}
        cands = self.matcher.score_all(desc, d.get("typed_uom"))
        top = cands[0] if cands else None
        second = cands[1].score if len(cands) > 1 else 0
        if top and top.score >= 0.9 and top.score - second >= 0.06:
            d.update(item_code=top.item_code, item_desc=top.description, uom=top.uom, match_score=top.score)
            st["matched_note"] = f"Matched “{desc}” to **{top.item_code} {top.description}** ({top.uom})."
            return None
        shown = [c for c in cands[:4] if c.score >= 0.4][:3]
        if shown:
            st["candidates"] = [{"item_code": c.item_code, "description": c.description, "uom": c.uom, "category": c.category, "score": c.score} for c in shown]
            st["awaiting"] = "item_choice"
            st["last_question"] = "Which of these items do you mean?"
            q = [{"label": f"{c.item_code} · {c.description}", "value": c.item_code} for c in shown]
            q.append({"label": "None of these (new item)", "value": "none of these, it's a new item"})
            lead = f"“{desc}” could be more than one item." if len(shown) > 1 else f"Did you mean this item for “{desc}”?"
            return {"text": lead + " Which one do you mean?", "candidates": st["candidates"], "quick_replies": q}
        st["awaiting"] = "new_item_confirm"
        st["last_question"] = "This is not in the item master. Is it a new item?"
        d["not_found"] = True
        return {"text": f"I can't find “{desc}” in the item master. If it's something we haven't bought before, I can raise it as a "
                        "**new item** (it goes to sourcing). Otherwise, describe it differently or give the item code.",
                "quick_replies": [{"label": "Yes, it's a new item", "value": "none of these, it's a new item"}]}

    def _next(self, st: dict, confirm: bool = False) -> dict:
        d = st["draft"]
        notes = []
        if st.get("awaiting") == "new_item_confirm" and (confirm or st.get("_force_new")):
            d["is_new"] = True
        if st.get("awaiting") == "new_item_confirm" and not d.get("is_new"):
            pass
        q = self._resolve_item(st)
        if st.pop("matched_note", None) and d.get("item_code"):
            notes.append(f"Matched to **{d['item_code']} {d['item_desc']}** ({d['uom']}).")
        note = st.pop("note", None)
        if note:
            notes.append(note)
        if q:
            q["text"] = " ".join(notes + [q["text"]]).strip()
            q["draft"] = self.view(d)
            return q

        unit = d.get("uom") or d.get("typed_uom") or "units"
        if d.get("typed_uom") and d.get("uom") and d["typed_uom"] != d["uom"]:
            notes.append(f"Note: this item is stocked in {d['uom']}, so I'll use {d['uom']}.")
            d["typed_uom"] = d["uom"]
        ask = None
        if not d.get("quantity") or d["quantity"] <= 0:
            if d.get("quantity") is not None and d["quantity"] <= 0:
                notes.append("Quantity must be more than zero.")
            ask = ("quantity", f"How many {unit} do you need?", [])
        elif not d.get("plant"):
            ask = ("plant", "Which plant is this for?", [{"label": f"{k} · {v}", "value": k} for k, v in self.plants.items()])
        elif not d.get("need_by_date"):
            nxt = self.today + timedelta(days=7)
            ask = ("need_by", "By when do you need it?", [{"label": "In 1 week", "value": f"by {nxt.isoformat()}"},
                                                          {"label": "In 2 weeks", "value": f"by {(self.today + timedelta(days=14)).isoformat()}"}])
        elif d.get("need_by_date") and date.fromisoformat(d["need_by_date"]) < self.today:
            notes.append(f"{_fmt_date(d['need_by_date'])} is in the past.")
            d.pop("need_by_date")
            ask = ("need_by", "Which date do you need it by?", [])
        elif not d.get("urgency"):
            if d.get("urgency_hint"):
                ask = ("urgent_confirm", "You mentioned it's urgent. Should I mark this PR as an **Emergency**? Emergency PRs can be bought "
                       "without quotes up to the policy limit, so use it only for genuine breakdowns.",
                       [{"label": "Yes, Emergency", "value": "emergency"}, {"label": "No, Normal", "value": "normal"}])
            else:
                ask = ("urgency", "Is this an emergency or normal priority?", [{"label": "Normal", "value": "normal"}, {"label": "Emergency", "value": "emergency"}])
        elif d.get("is_new") and d.get("estimated_unit_price") is None:
            ask = ("new_item_price", "Since this is a new item, what's your estimated price per unit (₹)? Sourcing uses it to value the request.", [])
        if ask:
            st["awaiting"], st["last_question"] = ask[0], ask[1]
            return {"text": " ".join(notes + [ask[1]]).strip(), "quick_replies": ask[2], "draft": self.view(d)}

        st["awaiting"] = "confirm"
        st["last_question"] = "Shall I raise this PR?"
        if confirm and st.get("ready_shown"):
            return {"text": "", "commit": True, "draft": self.view(d)}
        st["ready_shown"] = True
        return {"text": " ".join(notes + ["Here's the PR. Shall I raise it?"]).strip(), "ready": True, "draft": self.view(d),
                "quick_replies": [{"label": "Confirm & raise PR", "value": "confirm"}, {"label": "Change something", "value": "I want to change something"}]}

    def view(self, d: dict) -> dict:
        return {
            "item_code": d.get("item_code") or ("NEW" if d.get("is_new") else None),
            "item_description": d.get("item_desc") or d.get("description"),
            "typed_description": d.get("description"),
            "quantity": d.get("quantity"), "uom": d.get("uom") or d.get("typed_uom"),
            "plant": d.get("plant"), "plant_name": self.plants.get(d.get("plant") or "", ""),
            "need_by_date": d.get("need_by_date"), "urgency": d.get("urgency"),
            "estimated_unit_price": d.get("estimated_unit_price"), "is_new": bool(d.get("is_new")),
        }

    def next_from_queue(self, st: dict) -> tuple[dict | None, dict]:
        """After a PR is raised, start the next queued item, keeping plant/date/urgency."""
        prev = st.get("draft", {})
        queue = st.get("queue", [])
        st = {"draft": {}, "queue": queue[1:] if queue else []}
        if not queue:
            return None, st
        nxt = queue[0]
        st["draft"] = {"description": nxt.get("description"), "quantity": nxt.get("quantity"), "typed_uom": nxt.get("uom"),
                       "estimated_unit_price": nxt.get("estimated_unit_price"), "plant": prev.get("plant"),
                       "need_by_date": prev.get("need_by_date"), "urgency": prev.get("urgency")}
        reply = self._next(st)
        reply["text"] = f"Next item: “{nxt.get('description')}”. " + reply["text"]
        return reply, st


__all__ = ["ChatEngine", "regex_extract", "normalise"]
