"""Update data/sessions.json and data/rooms.csv from a newly saved catalog HTML without losing past days.

Usage:  python scripts/merge_catalog.py ["data/Session Catalog AI World.html"] [--dry-run]

Why: the catalog page drops the date and time from the tiles of days that are over, so a page saved after a day
has passed has no dates for that day and the normal parser (python -m app.catalog_parser) would silently drop all of
those sessions. This script keeps the data you already have for them:

  * a session whose tile has a date in the new file takes the new data (new sessions, time changes, new text);
  * a session whose tile has no date keeps its current data (and is reported if its day is still to come);
  * a session in the current data that is missing from the file, on a day that is not over, is removed (cancelled);
  * rooms follow the same rule (the room line of a tile is used when the tile has one, otherwise the old row stays).

It prints a summary and refuses to write when something looks wrong (for example far fewer sessions than before).
"""
from __future__ import annotations

import csv
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.catalog_parser import CatalogHTMLParser  # noqa: E402
from scripts.import_rooms_from_catalog import FIELDS, parse_location  # noqa: E402

DATA = ROOT / "data"
DEFAULT_HTML = DATA / "Session Catalog AI World.html"
COMPARE = ("title", "date", "startTime", "endTime", "dateLabel", "description", "sessionType", "timezone", "notes",
           "deliveryTypes", "areasOfInterest", "contentArea", "audienceLevel", "industries", "jobRoles")


def base_id(tile_id: str | None) -> str | None:
    """The catalog gives every repeat of a session its own tile id ('session-<id>-<repeat id>'); keep the first part."""
    return "-".join(tile_id.split("-")[:2]) if tile_id else tile_id


def read_tiles(html: Path) -> list[dict]:
    """All tiles of the page, each with its room line (`_room`) read from the same tile."""
    text = html.read_text(encoding="utf-8", errors="replace")
    parser = CatalogHTMLParser()
    parser.feed(text)
    parser.close()
    starts = [m.start() for m in re.finditer(r'<h4 class="rf-tile-title">', text)]
    if len(starts) != len(parser.sessions):
        raise SystemExit(f"The page has {len(starts)} tile titles but the parser found {len(parser.sessions)} tiles.")
    tiles = []
    for i, (s0, tile) in enumerate(zip(starts, parser.sessions)):
        seg = text[s0:(starts[i + 1] if i + 1 < len(starts) else len(text))]
        room = re.search(r'session-time-in-person"[^>]*>([^<]*)<', seg)
        if tile.get("title") and tile.get("code"):
            tiles.append(dict(tile, _room=room.group(1).strip() if room else "",
                              id=base_id(tile.get("id")), externalId=(base_id(tile.get("id")) or "").removeprefix("session-") or None))
    return tiles


def _end(s: dict) -> datetime:
    return datetime.fromisoformat(f"{s['date']}T{s.get('endTime') or s.get('startTime') or '23:59'}")


def pick_occurrence(options: list[dict], now: datetime) -> dict:
    """One row per session code: the earliest occurrence that is not over yet (else the latest one)."""
    options = sorted(options, key=lambda t: (t["date"], t.get("startTime") or ""))
    return next((t for t in options if _end(t) >= now), options[-1])


def merge(current: list[dict], tiles: list[dict], today: str, now: datetime | None = None) -> tuple[list[dict], dict]:
    """(merged sessions, report). Dated tiles take the data of their earliest open occurrence; undated ones keep ours."""
    now = now or datetime.fromisoformat(f"{today}T00:00")
    cur = {s["code"]: s for s in current}
    dated: dict[str, list[dict]] = {}
    undated: dict[str, dict] = {}
    for t in tiles:
        if t.get("date"):
            dated.setdefault(t["code"], []).append(t)
        else:
            undated[t["code"]] = t
    rep: dict = {"added": [], "changed": [], "kept": [], "removed": [], "check": [], "moved": [], "unchanged": 0, "repeats": 0}
    out: dict[str, dict] = {}
    for code, options in dated.items():
        rep["repeats"] += len(options) > 1
        t = pick_occurrence(options, now)
        old = cur.get(code)
        if old is None:
            rep["added"].append(code)
        else:
            diff = [k for k in COMPARE if old.get(k) != t.get(k)]
            if diff:
                rep["changed"].append((code, diff))
            else:
                rep["unchanged"] += 1
        out[code] = t
    for code, old in cur.items():
        if code in out:
            continue
        past = (old.get("date") or "9999") < today
        days = [k for k in undated.get(code, {}).get("rawClasses", []) if k.startswith("day-")]
        if code in undated and not past and len(days) == 1 and _day_over(days[0], today):
            # our data puts it on a day to come, but the catalog files it under a day that is over and gives no time:
            # the slot we have is wrong and the real one is unknown, and the day is over, so the session is dropped
            rep["moved"].append(code)
        elif code in undated or past:
            out[code] = old  # no date in the new file (the day is over), or an earlier day: keep what we have
            rep["kept"].append(code)
            if code in undated and not past and not any(_day_over(k, today) for k in days):
                rep["check"].append(code)
        else:
            rep["removed"].append(code)  # on a day still to come, but gone from the catalog
    merged = sorted(out.values(), key=lambda s: (s.get("date") or "", s.get("startTime") or "", s["code"]))
    return merged, rep


def _class_date(day_class: str) -> str | None:
    """'day-monday-oct-26' -> '2026-10-26'."""
    m = re.match(r"day-[a-z]+-oct-(\d+)", day_class)
    return f"2026-10-{int(m.group(1)):02d}" if m else None


def _day_over(day_class: str, today: str) -> bool:
    """True when the day of a 'day-...' class is before today."""
    d = _class_date(day_class)
    return bool(d) and d < today


def merge_rooms(old_rows: dict[str, dict], tile_rooms: dict[str, str], keep: set[str], today: str) -> dict[str, dict]:
    """Room rows for the kept sessions: the new room line of a tile when it has one, else the old row."""
    rows = {c: r for c, r in old_rows.items() if c in keep}
    for code, text in tile_rooms.items():
        if code in keep:
            rows[code] = {"code": code, **parse_location(text), "source": "catalog-html", "capturedAt": today}
    return rows


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    html = Path(args[0]) if args else DEFAULT_HTML
    dry = "--dry-run" in sys.argv
    today = date.today().isoformat()
    payload = json.loads((DATA / "sessions.json").read_text(encoding="utf-8"))
    current = payload["sessions"]
    tiles = read_tiles(html)
    merged, rep = merge(current, tiles, today)

    print(f"Catalog file: {html.name}: {len(tiles)} tiles, {sum(1 for t in tiles if t.get('date'))} with a date")
    print(f"Sessions: {len(current)} before, {len(merged)} after")
    print(f"  added {len(rep['added'])}: {', '.join(rep['added'][:12])}")
    print(f"  changed {len(rep['changed'])}: " + "; ".join(f"{c} ({', '.join(d)})" for c, d in rep["changed"][:20]))
    print(f"  unchanged {rep['unchanged']}, kept without a date {len(rep['kept'])}, sessions that repeat on several days {rep['repeats']}")
    print(f"  removed (day still to come, gone from the file) {len(rep['removed'])}: {', '.join(rep['removed'])}")
    if rep["moved"]:
        print(f"  DROPPED: the catalog now files these under a day that is over, without a time: {', '.join(rep['moved'])}")
    if rep["check"]:
        print(f"  CHECK undated tiles for days still to come, kept as they are: {', '.join(rep['check'][:10])}")

    problems = []
    if len(merged) < 0.9 * len(current):
        problems.append(f"the merge has {len(merged)} sessions, fewer than 90% of the {len(current)} you have")
    if len(rep["removed"]) > max(10, 0.05 * len(current)):
        problems.append(f"{len(rep['removed'])} sessions would be removed")
    if problems:
        print("REFUSING TO WRITE: " + "; ".join(problems))
        return 1
    if dry:
        print("Dry run: nothing written.")
        return 0

    keep = {s["code"] for s in merged}
    old_rows = {r["code"]: r for r in csv.DictReader((DATA / "rooms.csv").open(encoding="utf-8", newline=""))}
    new_rooms = {s["code"]: s["_room"] for s in merged if s.get("_room")}
    rooms = merge_rooms(old_rows, new_rooms, keep, today)
    for s in merged:
        s.pop("_room", None)
    with (DATA / "rooms.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for code in sorted(rooms):
            w.writerow(rooms[code])
    payload["catalog"].update({
        "snapshotFile": html.name, "importedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "sessionCount": len(merged),
        "note": f"Merged on {today}: days that were already over keep the data of the earlier capture.",
    })
    payload["sessions"] = merged
    (DATA / "sessions.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(merged)} sessions and {len(rooms)} rooms.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
