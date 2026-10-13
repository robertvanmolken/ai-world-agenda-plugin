"""Venue model: resolve session rooms to zones and estimate walking time between them.

All minutes are rough estimates (the official maps have no scale). See data/venue.json.
"""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
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


def load_not_in_app(path: str | Path | None = None) -> dict[str, dict[str, str]]:
    """Read not_in_app.csv into {session code: row}: sessions listed in the catalog but absent from the app."""
    f = Path(path) if path else DATA_DIR / "not_in_app.csv"
    if not f.exists():
        return {}
    with f.open(encoding="utf-8", newline="") as fh:
        return {row["code"].strip().upper(): row for row in csv.DictReader(fh) if row.get("code")}


def mark_not_in_app(sessions: list[dict[str, Any]], missing: dict[str, dict[str, str]]) -> None:
    """Flag sessions that were not found in the mobile app (inApp=False plus a note), in place."""
    for s in sessions:
        row = missing.get((s.get("code") or "").upper())
        if row:
            s["inApp"] = False
            s["appNote"] = (row.get("note") or "Not found in the mobile app") + ", checked " + (row.get("checkedAt") or "")
            s["appNote"] = s["appNote"].rstrip(", ")


def load_overrides(path: str | Path | None = None) -> dict[str, dict[str, str]]:
    """Read session_overrides.csv into {session code: row}: time corrections taken from the mobile app."""
    f = Path(path) if path else DATA_DIR / "session_overrides.csv"
    if not f.exists():
        return {}
    with f.open(encoding="utf-8", newline="") as fh:
        return {row["code"].strip().upper(): row for row in csv.DictReader(fh) if row.get("code")}


def apply_overrides(sessions: list[dict[str, Any]], overrides: dict[str, dict[str, str]]) -> None:
    """Replace date and times on sessions in place and set timeCorrected=True."""
    for s in sessions:
        row = overrides.get((s.get("code") or "").upper())
        if not row:
            continue
        d = datetime.strptime(row["date"].strip(), "%Y-%m-%d")
        s["date"] = d.strftime("%Y-%m-%d")
        s["dateLabel"] = f"{d.strftime('%A')}, {d.strftime('%b')} {d.day}"
        s["startTime"] = row["startTime"].strip()
        s["endTime"] = row["endTime"].strip()
        s["timeCorrected"] = True


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


def travel_minutes(a: str, b: str) -> tuple[int, int]:
    """(best, worst) estimated minutes, including the buffer. Hub = range over candidate halls."""
    if a == "hub" and b == "hub":
        lo = hi = venue()["model"]["sameZoneMinutes"]
    else:
        vals = [_walk(x, y) for x in _candidates(a) for y in _candidates(b)]
        lo, hi = min(vals), max(vals)
    buf = venue()["model"]["bufferMinutes"]
    return lo + buf, hi + buf


def _mins(t: str) -> int:
    h, m = map(int, t.split(":"))
    return h * 60 + m


def _label(zone: str) -> str:
    return venue()["hub"]["name"] if zone == "hub" else venue()["zones"][zone]["name"]


def assess_transition(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
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
    gone = [x.get("code") for x in (first, second) if x.get("inApp") is False]
    if gone:
        out.update(verdict="unknown", reason=f"Not found in the mobile app: {', '.join(gone)}. It may be cancelled or moved.")
        return out
    za, zb = session_zone(first), session_zone(second)
    if not za or not zb:
        out.update(verdict="unknown", reason="Room not yet published for one or both sessions.")
        return out
    lo, hi = travel_minutes(za, zb)
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
    levels = {venue()["zones"][z]["level"] for z in _candidates(za) + _candidates(zb)}
    out["route"] = f"{_label(za)} -> {_label(zb)}" + (" (via escalator/elevator)" if len(levels) > 1 else "")
    if "hub" in (za, zb):
        out["note"] = "The Oracle AI World Hub location is unconfirmed, so this is a range over Halls A-D and G."
    return out
