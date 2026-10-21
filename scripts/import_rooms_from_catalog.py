"""Build data/rooms.csv from the room line ('Marco Polo 803, Level 1') of each tile in a saved catalog HTML.

Usage: python scripts/import_rooms_from_catalog.py ["data/Session Catalog AI World.html"]
"""
from __future__ import annotations

import csv
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HTML = ROOT / "data" / "Session Catalog AI World.html"
FIELDS = ["code", "room", "area", "level", "location", "source", "capturedAt"]
HUB = "Oracle AI World Hub"
CSC = "Customer Success Central"
HUB_LEVEL = "2"  # all Hub theaters are on Level 2 (Level 1 is used for breakfast and lunch)


def parse_location(text: str) -> dict[str, str]:
    """Split a catalog room line into room, area and level. The Hub and its theaters are on Level 2."""
    loc = re.sub(r"\s+", " ", text).strip()
    low = loc.lower()
    parts = [p.strip() for p in loc.split(",")]
    level = ""
    if len(parts) > 1 and re.fullmatch(r"Level \d", parts[1]) and "foyer" not in low:
        level = parts[1][-1]
    head = parts[0]
    if "customer success" in low:
        return {"room": head, "area": CSC, "level": HUB_LEVEL, "location": loc}
    if "hub" in low:
        if re.fullmatch(r"(?i)(oracle )?(ai world )?hub", head) or "foyer" in low:
            return {"room": "Hub", "area": HUB, "level": HUB_LEVEL, "location": loc}
        return {"room": head, "area": HUB, "level": HUB_LEVEL, "location": loc}
    m = re.fullmatch(r"(Venetian Ballroom|Hall) (\S+)", head)
    if m:
        return {"room": m.group(2), "area": m.group(1), "level": level, "location": loc}
    m = re.fullmatch(r"(.+?) (\d+\S*)", head)
    if m:
        return {"room": m.group(2), "area": m.group(1), "level": level, "location": loc}
    return {"room": head, "area": head, "level": level, "location": loc}


def extract(html_text: str) -> dict[str, str]:
    starts = [m.start() for m in re.finditer(r'<h4 class="rf-tile-title">', html_text)]
    out: dict[str, str] = {}
    for i, p in enumerate(starts):
        seg = html_text[p:(starts[i + 1] if i + 1 < len(starts) else len(html_text))]
        code = re.search(r"\[([A-Z]{3}\d{3,5})\]", seg[:400])
        room = re.search(r'session-time-in-person"[^>]*>([^<]*)<', seg)
        if code and room and room.group(1).strip():
            out[code.group(1)] = room.group(1).strip()
    return out


def main(html_path: Path) -> int:
    rooms = extract(html_path.read_text(encoding="utf-8", errors="replace"))
    today = date.today().isoformat()
    with (ROOT / "data" / "rooms.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for code in sorted(rooms):
            w.writerow({"code": code, **parse_location(rooms[code]), "source": "catalog-html", "capturedAt": today})
    print(f"Wrote {len(rooms)} rooms from {html_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_HTML))
