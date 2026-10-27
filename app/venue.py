"""Venue model: resolve session rooms to zones and estimate walking time between them.

All minutes are rough estimates (the official maps have no scale). See data/venue.json.
"""
from __future__ import annotations

import csv
import json
import math
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

# Hands-on sessions need a laptop set up, so people arrive early (experience, not from the catalog).
EARLY_TYPES = {"Hands On Lab", "Product Bootcamp", "Hackathon"}
EARLY_MINUTES = 30


def needs_early(s: dict[str, Any]) -> bool:
    return (s.get("sessionType") or "") in EARLY_TYPES


def early_note(gap: int, hi: int, minutes: int = EARLY_MINUTES) -> str:
    """Explain what the gap leaves of the early arrival."""
    spare = max(0, gap - hi)
    if spare >= minutes:
        return f"Hands-on session: arrive about {minutes} min early to set up. This gap allows it."
    return (f"Hands-on session: it is best to arrive about {minutes} min early to set up. With this gap you would "
            f"arrive about {spare} min before the start, so expect to settle in quickly.")
HUB_AREAS = {"oracle ai world hub", "customer success central"}


@lru_cache(maxsize=1)
def venue() -> dict[str, Any]:
    return json.loads((DATA_DIR / "venue.json").read_text(encoding="utf-8"))


def load_rooms(path: str | Path | None = None) -> dict[str, dict[str, str]]:
    """Read rooms.csv into {session code: row}. Missing file -> empty."""
    f = Path(path) if path else DATA_DIR / "rooms.csv"
    if not f.exists():
        return {}
    with f.open(encoding="utf-8", newline="") as fh:
        return {row["code"].strip().upper(): row for row in csv.DictReader(fh) if row.get("code")}


def merge_rooms(sessions: list[dict[str, Any]], rooms: dict[str, dict[str, str]]) -> None:
    """Add room, area, level and roomLocation to sessions in place."""
    for s in sessions:
        row = rooms.get((s.get("code") or "").upper())
        if row:
            s["room"] = row.get("room") or ""
            s["area"] = row.get("area") or ""
            s["level"] = int(row["level"]) if (row.get("level") or "").strip() else None
            s["roomLocation"] = row.get("location") or ""
            s["roomSource"] = row.get("source") or ""


def resolve_zone(room: str, area: str, level: int | None) -> str | None:
    """Return a zone id, 'hub', or None when the room is not on the venue map."""
    v = venue()
    a = (area or "").strip().lower()
    if a in HUB_AREAS:
        return "hub"
    zones = v["zones"]
    if a == "venetian ballroom":
        return "venetian_ballroom"
    if (area or "").strip().lower() == "hall":
        zid = "hall_" + (room or "").strip().lower()
        return zid if zid in zones else None
    m = re.match(r"\d+", (room or "").strip())
    if m:
        n = int(m.group())
        for zid, z in zones.items():
            if level is not None and z["level"] != level:
                continue
            if any(lo <= n <= hi for lo, hi in z.get("ranges", [])):
                return zid
    return None


def session_room(s: dict[str, Any], zone: str | None) -> str | None:
    """Room key on the plan for a session ('2204', or 'T3' for Hub theater 3), or None for halls."""
    from .routing import room_key

    return room_key(zone, s.get("room")) if zone else None


def session_zone(s: dict[str, Any]) -> str | None:
    if not s.get("room"):
        return None
    return resolve_zone(s.get("room", ""), s.get("area", ""), s.get("level"))


def _walk(a: str, b: str) -> int:
    """Estimated minutes between two concrete zones, excluding buffer."""
    v = venue()
    m, za, zb = v["model"], v["zones"][a], v["zones"][b]
    if a == b:
        return m["sameZoneMinutes"]
    if za["level"] == zb["level"]:
        minutes = m["sameLevelBaseMinutes"] + abs(za["x"] - zb["x"])
        return round(min(minutes, m.get("sameLevelMaxMinutes", minutes)))
    return round(m["levelChangeBaseMinutes"] + za["x"] + m["levelChangeMinutes"] + zb["x"])


def _candidates(zone: str) -> list[str]:
    return venue()["hub"]["candidates"] if zone == "hub" else [zone]


def travel_minutes(a: str, b: str, step_free: bool = False, room_a: str | None = None, room_b: str | None = None) -> tuple[int, int]:
    """(best, worst) estimated minutes, including the buffer. Hub = range over candidate halls."""
    if a == "hub" and b == "hub" and not (room_a or room_b):
        lo = hi = venue()["model"]["sameZoneMinutes"]
    else:
        from .routing import route_range  # local import: routing imports this module

        r = route_range(a, b, step_free, room_a, room_b)
        if r:
            lo, hi = max(1, math.floor(r["bestMinutes"])), max(1, math.ceil(r["worstMinutes"]))
        else:  # zone missing from the walking graph: fall back to the coarse model
            vals = [_walk(x, y) for x in _candidates(a) for y in _candidates(b)]
            lo, hi = min(vals), max(vals)
    buf = venue()["model"]["bufferMinutes"]
    return lo + buf, hi + buf


def _mins(t: str) -> int:
    h, m = map(int, t.split(":"))
    return h * 60 + m


def _label(zone: str) -> str:
    return venue()["hub"]["name"] if zone == "hub" else venue()["zones"][zone]["name"]


def _hub_note(r: dict[str, Any]) -> dict[str, Any]:
    """Say so when a walk ends at a Hub booth whose position is only estimated from its row neighbours."""
    from .routing import hub_estimated

    est = [k for k in (r.get("fromRoom"), r.get("toRoom")) if k and hub_estimated(k)]
    return {"estimatedPosition": est, "positionNote": "The position of " + ", ".join(f"booth {k}" for k in est) +
            " is estimated from the booths next to it, so the walk is only a rough guide."} if est else {}


def route_details(a: str, b: str, step_free: bool = False, room_a: str | None = None, room_b: str | None = None) -> dict[str, Any] | None:
    """Steps, levels, distance and map link for a walk between two zones (None when not routable)."""
    from .routing import route_range

    r = route_range(a, b, step_free, room_a, room_b)
    if not r:
        return None
    from .routing import data_version

    sf = ("&stepFree=1" if step_free else "") + (f"&fromRoom={r['fromRoom']}" if r.get("fromRoom") else "") + (f"&toRoom={r['toRoom']}" if r.get("toRoom") else "")
    return {
        "stepFree": step_free,
        "steps": r["steps"], "levels": r["levels"], "meters": r["meters"], "polylines": r["polylines"],
        "mapUrls": [
            {"level": lv, "label": "Hub plan" if lv == 6 else f"Level {lv}",
             "url": f"/venue/route?from={r['from']}&to={r['to']}&level={lv}{sf}&v={data_version()}",
             "pngUrl": f"/venue/route.png?from={r['from']}&to={r['to']}&level={lv}{sf}&v={data_version()}"}
            for lv in r["levels"]
        ],
        "pageUrl": f"/venue/route/page?from={r['from']}&to={r['to']}{sf}",
        "viaHub": "hub" in (a, b),
        **_hub_note(r),
    }


def late_minutes(gap: int, best: int, worst: int) -> dict[str, int]:
    """Minutes late on arrival for the best and worst walking estimate (0 when there is time to spare)."""
    return {"best": max(0, best - gap), "worst": max(0, worst - gap)}


def resolve_place(text: str) -> str | None:
    """Turn free text like 'Hall G', 'Hub', 'Galileo 1001, Level 1' or 'Titian' into a zone id."""
    t = (text or "").strip().lower()
    if not t:
        return None
    if "hub" in t or "customer success" in t or re.search(r"theater\s*\d", t):
        return "hub"
    from .hub import find_areas, find_booths, match_company

    if re.fullmatch(r"(?:(?:booth|stand)\s*)?\d{4,5}", t) and find_booths(t, 1):
        return "hub"
    if match_company(t) or re.match(r"(?:booth|stand)\s+\d{4,5}\b", t) or find_areas(t, 1):
        return "hub"
    zones = venue()["zones"]
    for zid, z in zones.items():
        if t == z["name"].lower() or t == zid:
            return zid
    lvl = re.search(r"level\s*(\d)", t)
    level = int(lvl.group(1)) if lvl else None
    if t.startswith("hall "):
        return resolve_zone(t[5:].split(",")[0].strip(), "Hall", level)
    num = re.search(r"\d{3,4}", t)
    if num:
        n = int(num.group())
        for zid, z in zones.items():
            if level is not None and z["level"] != level:
                continue
            if any(lo <= n <= hi for lo, hi in z.get("ranges", [])):
                return zid
    for zid, z in zones.items():
        if z["name"].lower() in t:
            return zid
    return None


def check_move(from_place: str, to_place: str, gap_minutes: int, step_free: bool = False) -> dict[str, Any]:
    """Walking check between two free-text places (for lunch, networking or any custom stop)."""
    from .routing import place_room

    za, zb = resolve_place(from_place), resolve_place(to_place)
    out: dict[str, Any] = {"from": from_place, "to": to_place, "gapMinutes": gap_minutes, "estimate": True}
    if not za or not zb:
        out.update(verdict="unknown", reason="Could not place: " + ", ".join(p for p, z in ((from_place, za), (to_place, zb)) if not z))
        return out
    lo, hi = travel_minutes(za, zb, step_free, place_room(from_place, za), place_room(to_place, zb))
    out["stepFree"] = step_free
    out.update(
        estimatedMinutes={"best": lo, "worst": hi},
        lateIfWalking=late_minutes(gap_minutes, lo, hi),
        route=f"{_label(za)} -> {_label(zb)}",
    )
    out["verdict"] = "overlap" if gap_minutes < 0 else "ok" if hi <= gap_minutes else "tight" if lo <= gap_minutes else "unlikely"
    if out["verdict"] == "unlikely" and za == zb:
        out["verdict"] = "tight"  # same block: the rooms are next to each other
        out["reason"] = "Both places are in the same block, so they are close together. Expect to arrive right at the start."
    if "hub" in (za, zb):
        out["note"] = "The Oracle AI World Hub is on Level 2, in Hall C. Booth and theater positions on its plan are approximate."
    return out


def assess_transition(a: dict[str, Any], b: dict[str, Any], step_free: bool = False, early_arrival: bool = True) -> dict[str, Any]:
    """Can someone get from the end of session a to the start of session b?

    Verdict: ok (worst case fits), tight (only the best case fits), unlikely (even best case
    does not fit), overlap (sessions overlap), unknown (missing time or room).
    """
    out: dict[str, Any] = {"from": a.get("code"), "to": b.get("code"), "estimate": True}
    if a.get("date") != b.get("date") or not (a.get("endTime") and b.get("startTime")):
        out.update(verdict="unknown", reason="Missing date or time, or different days.")
        return out
    first, second = (a, b) if a["startTime"] <= b["startTime"] else (b, a)
    out["from"], out["to"] = first.get("code"), second.get("code")
    gap = _mins(second["startTime"]) - _mins(first["endTime"])
    out["gapMinutes"] = gap
    if gap < 0:
        out.update(verdict="overlap", reason="The sessions overlap in time.")
        return out
    za, zb = session_zone(first), session_zone(second)
    if not za or not zb:
        out.update(verdict="unknown", reason="Room not yet published for one or both sessions.")
        return out
    ra, rb = session_room(first, za), session_room(second, zb)
    lo, hi = travel_minutes(za, zb, step_free, ra, rb)
    out["stepFree"] = step_free
    out.update(
        fromRoom=first.get("roomLocation") or first.get("room"),
        toRoom=second.get("roomLocation") or second.get("room"),
        estimatedMinutes={"best": lo, "worst": hi},
    )
    if hi <= gap:
        out["verdict"] = "ok"
    elif lo <= gap:
        out["verdict"] = "tight"
    else:
        out["verdict"] = "unlikely"
        if za == zb:
            # same block: the rooms are next to each other, so at worst you arrive a moment late
            out["verdict"] = "tight"
            out["reason"] = ("Both sessions are in the same block, so the rooms are close together. "
                             + ("They are back to back, so expect to arrive right at the start." if gap == 0
                                else "Expect to arrive right at the start."))
        elif gap == 0:
            out["reason"] = "The sessions are back to back, so there is no time to move between the rooms."
    if early_arrival and needs_early(second):
        out["arriveEarlyMinutes"] = EARLY_MINUTES
        out["arriveBy"] = f"{(_mins(second['startTime']) - EARLY_MINUTES) // 60:02d}:{(_mins(second['startTime']) - EARLY_MINUTES) % 60:02d}"
        out["earlyNote"] = early_note(gap, hi)
        if out["verdict"] == "ok" and gap - hi < EARLY_MINUTES:  # soft rule: still possible, but not the early arrival
            out["verdict"] = "tight"
            out["reason"] = out["earlyNote"]
    levels = {venue()["zones"][z]["level"] for z in _candidates(za) + _candidates(zb)}
    out["lateIfWalking"] = late_minutes(gap, lo, hi)
    out["route"] = f"{_label(za)} -> {_label(zb)}" + ((" (via elevator)" if step_free else " (via escalator/elevator)") if len(levels) > 1 else "")
    detail = route_details(za, zb, step_free, ra, rb)
    if detail:
        out["routeDetail"] = detail
    if "hub" in (za, zb):
        out["note"] = "The Oracle AI World Hub is on Level 2, in Hall C. Booth and theater positions on its plan are approximate."
    return out
