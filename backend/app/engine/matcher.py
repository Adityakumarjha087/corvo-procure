"""Item matching (policy section 1).

Deterministic and explainable: the score combines spec tokens (sizes, grades, part numbers,
which must agree), word overlap after expanding shop-floor short forms, and a fuzzy ratio.
The same matcher serves the batch engine and the chat assistant (which shows the candidates).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from .model import Item

NOISE_PATTERNS = [
    r"\(\s*repeat\s*\)", r"\brepeat(?: order)?\b", r"\bas per (?:the )?sample\b", r"\bas per (?:drawing|spec)\b",
    r"[-–]\s*urgent\b", r"\burgent(?:ly)?\b", r"\basap\b", r"\bimmediately\b", r"\bfor (?:maintenance|production|stores|tool room|qc|quality)\b",
    r"\bplease\b", r"\bpls\b", r"\bplz\b", r"\brequired\b", r"\bneeded\b", r"\bneed\b",
]
ABBREVIATIONS = {
    "brg": "bearing", "brgs": "bearing", "bearings": "bearing", "hyd": "hydraulic", "hydr": "hydraulic",
    "pneu": "pneumatic", "pneum": "pneumatic", "cyl": "cylinder", "elec": "electrical", "rod": "electrode",
    "rods": "electrode", "electrodes": "electrode", "gloves": "glove", "glove": "glove", "shoes": "shoe",
    "boxes": "box", "bags": "bag", "bolts": "bolt", "nuts": "nut", "screws": "screw", "sheets": "sheet",
    "plates": "plate", "wheels": "wheel", "cylinders": "cylinder", "valves": "valve", "sensors": "sensor",
    "helmets": "helmet", "goggles": "goggle", "goggle": "goggle", "plugs": "plug", "monitors": "monitor",
    "laptops": "laptop", "mtr": "", "nos": "", "pcs": "", "qty": "", "ltr": "", "kgs": "",
    "alu": "aluminium", "aluminum": "aluminium", "al": "aluminium", "ss304": "ss 304",
    "keyboard": "keyboard", "kb": "keyboard", "mcb": "mcb", "ms": "ms",
}
STOPWORDS = {"for", "the", "of", "and", "a", "an", "with", "to", "in", "on", "type", "size", "item", "material", "&"}


def normalise(text: str) -> str:
    t = (text or "").lower()
    t = t.replace('"', " inch ").replace("''", " inch ").replace("”", " inch ").replace("″", " inch ")
    for p in NOISE_PATTERNS:
        t = re.sub(p, " ", t)
    t = re.sub(r"[()\[\],;:]", " ", t)
    t = re.sub(r"(?<=[a-z])-(?=[a-z])", " ", t)  # word-word hyphens
    t = re.sub(r"\s+-\s+|\s-$|^-\s", " ", t)
    words = []
    for w in t.split():
        w = ABBREVIATIONS.get(w, w)
        if w:
            words.extend(w.split())
    return " ".join(words).strip()


def _compact(t: str) -> str:
    return re.sub(r"[\s\-]", "", t)


def _specs(norm: str) -> list[str]:
    return [w for w in norm.split() if any(ch.isdigit() for ch in w)]


def _words(norm: str) -> set[str]:
    out = set()
    for w in norm.split():
        if any(ch.isdigit() for ch in w) or w in STOPWORDS or len(w) < 2:
            continue
        out.add(w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w)
    return out


@dataclass
class Candidate:
    item_code: str
    description: str
    score: float
    uom: str
    category: str


class ItemMatcher:
    def __init__(self, items: dict[str, Item]):
        self.items = items
        self._prep = []
        for it in items.values():
            n = normalise(it.description)
            self._prep.append((it, n, _compact(n), _specs(n), _words(n)))

    def score_all(self, description: str, uom: str | None = None) -> list[Candidate]:
        q = normalise(description)
        if not q:
            return []
        qc, qs, qw = _compact(q), _specs(q), _words(q)
        out = []
        for it, n, nc, ns, nw in self._prep:
            if q == n:
                s = 1.0
            else:
                spec_frac = (sum(1 for s_ in qs if s_.replace("-", "") in nc) / len(qs)) if qs else 0.85
                cand_spec = (sum(1 for s_ in ns if s_.replace("-", "") in qc) / len(ns)) if ns else 1.0
                overlap = len(qw & nw)
                word_cov = overlap / len(qw) if qw else (1.0 if qs and spec_frac == 1 else 0.0)
                cand_cov = overlap / len(nw) if nw else 1.0
                fz = fuzz.token_set_ratio(q, n) / 100.0
                s = 0.33 * spec_frac + 0.17 * cand_spec + 0.25 * word_cov + 0.10 * cand_cov + 0.15 * fz
                if qw and overlap == 0:
                    s *= 0.4
                if qs and spec_frac < 1:
                    s *= 0.75
            if uom:
                s += 0.03 if uom.upper() == it.uom.upper() else -0.05
            out.append(Candidate(it.item_code, it.description, round(min(s, 1.0), 4), it.uom, it.category))
        out.sort(key=lambda c: -c.score)
        return out

    def match(self, item_code: str | None, description: str, uom: str | None = None, min_score: float = 0.72) -> dict:
        """Return {item_code|None, method, score, candidates, ambiguous}."""
        code = (item_code or "").strip().upper()
        if code and code in self.items:
            return {"item_code": code, "method": "item_code", "score": 1.0, "candidates": [], "ambiguous": False}
        cands = self.score_all(description, uom)[:5]
        top = cands[0] if cands else None
        note = f"item code {code} not in item master; matched on description" if code else None
        if not top or top.score < min_score:
            return {"item_code": None, "method": "no_match", "score": top.score if top else 0.0,
                    "candidates": [c.__dict__ for c in cands[:3]], "ambiguous": False, "note": note}
        second = cands[1].score if len(cands) > 1 else 0.0
        return {"item_code": top.item_code, "method": "description", "score": top.score,
                "candidates": [c.__dict__ for c in cands[:3]], "ambiguous": (top.score - second) < 0.06, "note": note}
