"""Import the Oracle AI World Hub plan from data/room-screenshots/Hub_Floorplan_Editable.svg into data/venue_graph.json.

Usage:  python scripts/import_hub_svg.py [path/to/Hub_Floorplan_Editable.svg]

The SVG is a hand-traced reconstruction of the Hub floor plan photo (frame 1536 x 2048). From it this script takes:
  - every booth with a floor position (centre, size and rotation),
  - the 12 theater pills and the lettered Hub areas (A-H) with their markers, Oracle TV, SWAG Station and The Shop,
  - and it places booths without a position (the "needs placement" panel) next to their row neighbours, flagged
    "estimated" in roomStatus.
Rooms are stored as [x, y, w, h, rotation] (rotation in degrees about the centre). The graph file is edited as text,
only the Hub lines are replaced, so the compact formatting of the rest of the file stays as it is.
Also saves the plan photo in the same frame (hub-plan-photo.jpg) as the calibrator background.
"""
from __future__ import annotations

import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRAPH = ROOT / "data" / "venue_graph.json"
BOOTHS = ROOT / "data" / "hub_booths.json"
SHOTS = ROOT / "data" / "room-screenshots"
SVG = SHOTS / "Hub_Floorplan_Editable.svg"
PHOTO = SHOTS / "Hub_Floorplan_Enhanced_300DPI.jpg"
BACKGROUND = SHOTS / "hub-plan-photo.jpg"

NS = "{http://www.w3.org/2000/svg}"
FRAME = (1536, 2048)
VIEW = [100, 10, 1340, 2030]           # part of the frame the maps show
METERS_PER_PIXEL = 0.125               # a 10 ft booth is about 24 px
ENTRANCE = (268, 1928)                 # where the arrow on the plan enters the Hub (from Hall C)
STEP = 21.5                            # distance between neighbouring booth slots along a row (px)

# (key, label, x, y, w, h): lettered areas come from the markers on the plan and the legend of the info photo
ZONES = {"A": "AI Data Center Spotlight", "B": "Oracle AI Database", "C": "Oracle Cloud Infrastructure",
         "D": "Oracle Customer Success Central", "E": "Oracle AI Data Platform",
         "F": "Oracle Fusion Cloud and Industry Applications", "G": "Oracle Multicloud AI Database",
         "H": "Oracle Sports Spotlight"}
EXTRA_AREAS = {"ORACLE TV": ("Oracle TV", 539, 915, 70, 28), "SWAG STATION": ("SWAG Station", 1179, 610, 70, 40),
               "THE SHOP": ("The Shop at Oracle AI World", 1150, 1345, 90, 70),
               "ACE LOUNGE": ("ACE Lounge", 1150, 234, 90, 32),
               "MULTICLOUD LOUNGE": ("Oracle Multicloud AI Database lounge", 1150, 190, 110, 44)}


def _num(v: str | None, default: float = 0.0) -> float:
    return float(v) if v not in (None, "") else default


def read_svg(path: Path) -> dict:
    """booths {number: [x, y, w, h, rot]}, theaters {n: [x, y, w, h]}, zone markers {letter: (x, y)}."""
    root = ET.parse(path).getroot()
    booths: dict[str, list[float]] = {}
    for g in root.find(f".//{NS}g[@id='booths']"):
        number = g.get("data-booth-number")
        if not number or g.get("data-coordinate-space") != "floor":
            continue
        m = re.match(r"translate\(([-\d.]+)[ ,]([-\d.]+)\)(?:\s*rotate\(([-\d.]+)\))?", g.get("transform", ""))
        rect = g.find(f"{NS}rect")
        if not m or rect is None:
            continue
        cx, cy, rot = float(m.group(1)), float(m.group(2)), _num(m.group(3))
        w, h = float(rect.get("width")), float(rect.get("height"))
        booths[number] = [round(cx - w / 2, 1), round(cy - h / 2, 1), w, h, rot]
    theaters: dict[int, list[float]] = {}
    for g in root.find(f".//{NS}g[@id='theaters']").findall(f"{NS}g"):
        r = g.find(f"{NS}rect")
        theaters[int(g.get("data-theater-number"))] = [float(r.get(k)) for k in ("x", "y", "width", "height")]
    markers: dict[str, tuple[float, float]] = {}
    for g in root.find(f".//{NS}g[@id='zone-labels']").findall(f"{NS}g"):
        c = g.find(f"{NS}circle")
        if c is not None:
            markers[g.get("data-zone")] = (float(c.get("cx")), float(c.get("cy")))
    outline = root.find(f".//{NS}g[@id='floor-outline']/{NS}polygon")
    points = [[float(v) for v in p.split(",")] for p in outline.get("points").split()] if outline is not None else []
    return {"booths": booths, "theaters": theaters, "markers": markers, "outline": points}


def estimate(number: str, placed: dict[str, list[float]]) -> list[float] | None:
    """A position for a booth that is not on the plan: the nearest booth in its row, moved along the row."""
    row, slot = int(number) // 1000, int(number) % 100
    same = [(abs(int(n) % 100 - slot), n) for n in placed if int(n) // 1000 == row]
    if not same:
        return None
    gap, near = min(same, key=lambda t: (t[0], abs(int(t[1]) % 2 - slot % 2)))
    x, y, w, h, rot = placed[near]
    steps = (slot - int(near) % 100) * STEP
    a = math.radians(rot)
    return [round(x + math.sin(a) * steps, 1), round(y - math.cos(a) * steps, 1), w, h, rot]


def bounds(x: float, y: float, w: float, h: float, rot: float) -> tuple[float, float, float, float]:
    """Axis-aligned box around a rectangle rotated by rot degrees about its centre."""
    a = math.radians(rot)
    bw = abs(w * math.cos(a)) + abs(h * math.sin(a))
    bh = abs(w * math.sin(a)) + abs(h * math.cos(a))
    cx, cy = x + w / 2, y + h / 2
    return cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2


def build(svg_path: Path) -> dict:
    """All Hub data for the graph: rooms (x, y, w, h), rotations, labels, aliases and which positions are estimated."""
    data = read_svg(svg_path)
    wanted = {str(b["booth_number"]): b["name"] for b in json.loads(BOOTHS.read_text(encoding="utf-8"))}
    placed = {n: v for n, v in data["booths"].items() if n in wanted}
    rooms: dict[str, list[float]] = {}
    rotation: dict[str, float] = {}
    status: dict[str, str] = {}
    labels: dict[str, str] = {}
    for n in range(1, 13):
        x, y, w, h = data["theaters"][n]
        rooms[f"T{n}"] = [x, y, w, h]
        labels[f"T{n}"] = f"Theater {n}"
    for letter, title in ZONES.items():
        cx, cy = data["markers"][letter]
        rooms[f"Z{letter}"] = [round(cx - 26), round(cy - 26), 52, 52]
        labels[f"Z{letter}"] = f"Zone {letter}: {title}"
    for key, (title, cx, cy, w, h) in EXTRA_AREAS.items():
        rooms[key] = [round(cx - w / 2), round(cy - h / 2), w, h]
        labels[key] = title
    for number in sorted(wanted, key=int):
        v = placed.get(number)
        if v is None:
            v = estimate(number, placed)
            status[number] = "estimated"
        if v is None:
            continue
        rooms[number] = v[:4]
        if v[4]:
            rotation[number] = v[4]
    aliases = {f"THEATER {n}": [f"T{n}"] for n in range(1, 13)}
    aliases.update({f"ZONE {k}": [f"Z{k}"] for k in ZONES})
    boxes = [bounds(*r, rotation.get(k, 0)) for k, r in rooms.items()]
    return {"rooms": rooms, "rotation": rotation, "status": status, "labels": labels, "aliases": aliases, "outline": data["outline"],
            "extent": (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))}


def line_of(text: str, start: str) -> re.Match:
    m = re.search(r"^" + re.escape(start) + r".*$", text, re.M)
    assert m, f"line starting with {start!r} not found in the graph"
    return m


def replace_line(text: str, start: str, new: str) -> str:
    """Swap one line for new text, keeping the comma (or lack of one) at the end of the original line."""
    m = line_of(text, start)
    comma = "," if m.group(0).rstrip().endswith(",") else ""
    return text[: m.start()] + new.rstrip(",") + comma + text[m.end():]


def write_graph(h: dict) -> None:
    """Replace only the Hub lines of venue_graph.json (and add the Hub keys), leaving everything else untouched."""
    text = GRAPH.read_text(encoding="utf-8")
    x0, y0, x1, y1 = (round(v) for v in h["extent"])
    view = [max(0, x0 - 30), max(0, y0 - 40), x1 - x0 + 60, min(FRAME[1], y1 + 40) - max(0, y0 - 40)]
    ex, ey = ENTRANCE
    j = json.dumps
    level6 = {"name": "Oracle AI World Hub (Level 2)", "view": view, "metersPerPixel": METERS_PER_PIXEL, "outline": h["outline"]}
    text = replace_line(text, '    "6":', f'    "6": {j(level6)}')
    text = replace_line(text, '    "hub":         {"level": 6',
                        f'    "hub":         {{"level": 6, "x": {round(view[0] + view[2] / 2)}, "y": {round(view[1] + view[3] / 2)}, '
                        f'"type": "zone", "rect": {j(view)}}}')
    text = replace_line(text, '    "hub_entry":',
                        f'    "hub_entry":   {{"level": 6, "x": {ex}, "y": {ey}, "type": "junction", "label": "the Hub entrance"}}')
    text = replace_line(text, '    "hub": {', "    " + '"hub": ' + j(h["rooms"]))
    text = replace_line(text, '  "roomAliases":', '  "roomAliases": ' + j({"venetian_ballroom": {"HI": ["H", "I"]}, "hub": h["aliases"]}))
    text = replace_line(text, '  "roomLabels":', '  "roomLabels": ' + j({"hub": h["labels"]}))
    tail = '  "fixedMeters": {"hall_c|hub_entry": 40}'
    extra = '  "roomRotation": ' + j({"hub": h["rotation"]}) + ",\n  \"roomStatus\": " + j({"hub": h["status"]}) + ",\n"
    if '"roomRotation"' in text:
        text = replace_line(text, '  "roomRotation":', extra.split("\n")[0])
        text = replace_line(text, '  "roomStatus":', extra.split("\n")[1])
    else:
        text = text.replace(tail, extra + tail, 1)
    json.loads(text)  # must still be valid JSON before it is written
    GRAPH.write_text(text, encoding="utf-8")


def save_background() -> None:
    """The plan photo in the 1536 x 2048 frame the positions use (calibrator background)."""
    try:
        from PIL import Image

        Image.MAX_IMAGE_PIXELS = None
        Image.open(PHOTO).convert("RGB").resize(FRAME, Image.LANCZOS).save(BACKGROUND, quality=88)
        print(f"Wrote {BACKGROUND.name}")
    except (OSError, ImportError) as err:
        print(f"Could not save the background photo ({err}).")


def main() -> None:
    svg = Path(sys.argv[1]) if len(sys.argv) > 1 else SVG
    h = build(svg)
    write_graph(h)
    save_background()
    print(f"Hub imported: {sum(1 for k in h['rooms'] if k.isdigit())} booths ({len(h['status'])} estimated), "
          f"12 theaters, {len(ZONES)} zones, {len(EXTRA_AREAS)} extra areas.")


if __name__ == "__main__":
    main()
