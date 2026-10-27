"""Oracle AI World Hub: sponsor booths (number and company) and the lookups used for stand search and routing.

The booth list comes from the public exhibitor list (data/hub_booths.json). Booth number = row (thousands) and slot
(last two digits), for example 4009 is row 4, slot 9.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from .venue import DATA_DIR

_NOISE = {"booth", "stand", "the", "at", "to", "from", "oracle", "ai", "world", "hub"}


@lru_cache(maxsize=1)
def booths() -> dict[str, str]:
    """booth number -> company name."""
    rows = json.loads((DATA_DIR / "hub_booths.json").read_text(encoding="utf-8"))
    return {str(r["booth_number"]).strip(): str(r["name"]).strip() for r in rows}


def _norm(text: str) -> str:
    return " ".join(re.split(r"[^a-z0-9]+", (text or "").lower())).strip()


def booth_row(number: str) -> int:
    return int(number) // 1000


def booth_info(number: str) -> dict[str, Any] | None:
    name = booths().get(str(number))
    if name is None:
        return None
    n = int(number)
    return {"number": str(number), "name": name, "row": n // 1000, "slot": n % 100}


def booth_name(number: str) -> str:
    name = booths().get(str(number))
    return f"Booth {number} ({name})" if name else f"Booth {number}"


def find_booths(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Booths matching a number ('4009', 'booth 4009') or a company name (exact, then prefix, then contained)."""
    q = _norm(query)
    if not q:
        return []
    digits = re.fullmatch(r"(?:(?:booth|stand) )?(\d{4,5})", q)
    if digits:
        info = booth_info(digits.group(1))
        return [info] if info else []
    words = [w for w in q.split() if w not in ("booth", "stand")]
    q = " ".join(words)
    if len(q) < 2:
        return []
    exact, prefix, inside = [], [], []
    for num, name in booths().items():
        n = _norm(name)
        if n == q:
            exact.append(num)
        elif n.startswith(q):
            prefix.append(num)
        elif len(q) >= 3 and f" {q} " in f" {n} ":
            inside.append(num)
    ordered = exact + sorted(prefix, key=lambda x: _norm(booths()[x])) + sorted(inside, key=lambda x: _norm(booths()[x]))
    return [booth_info(n) for n in ordered[:limit]]


def match_company(text: str) -> str | None:
    """Booth number when the text is just a company name (optionally with 'booth' or 'stand' around it)."""
    q = " ".join(w for w in _norm(text).split() if w not in _NOISE)
    if len(q) < 3:
        return None
    for num, name in booths().items():
        if _norm(name) == q or " ".join(w for w in _norm(name).split() if w not in _NOISE) == q:
            return num
    return None
