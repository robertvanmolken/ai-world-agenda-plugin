"""Validate data/rooms.csv against the catalog and the venue map, and report sessions without a room.

Usage: python scripts/validate_rooms.py [--missing]
Exit code 1 when a row is invalid.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.catalog import load_catalog  # noqa: E402
from app.venue import DATA_DIR, load_rooms, resolve_zone  # noqa: E402


def validate() -> tuple[list[str], list[str]]:
    sessions = load_catalog(DATA_DIR / "sessions.json")["sessions"]
    by_code = {s["code"].upper(): s for s in sessions if s.get("code")}
    rooms = load_rooms()
    errors = []
    for code, row in rooms.items():
        if code not in by_code:
            errors.append(f"{code}: not in catalog")
            continue
        level = int(row["level"]) if (row.get("level") or "").strip() else None
        if not resolve_zone(row.get("room", ""), row.get("area", ""), level):
            errors.append(f"{code}: room '{row.get('room')}' ({row.get('area')}, level {level}) not on venue map")
    missing = sorted(c for c in by_code if c not in rooms)
    return errors, missing


if __name__ == "__main__":
    errs, miss = validate()
    for e in errs:
        print("ERROR", e)
    print(f"{len(load_rooms())} rooms, {len(miss)} sessions without a room")
    if "--missing" in sys.argv:
        print("\n".join(miss))
    sys.exit(1 if errs else 0)
