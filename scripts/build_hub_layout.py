"""Add the Oracle AI World Hub plan to data/venue_graph.json from data/hub_booths.json.

Usage:  python scripts/build_hub_layout.py [--photo data/room-screenshots/Hub_Floorplan_Enhanced_300DPI.jpg]

First run: writes the Hub (pseudo level 6), 12 theaters, a few areas and one rectangle per booth, and saves a
straightened copy of the plan photo (data/room-screenshots/hub-plan-straight.png) to use as the calibrator
background. The first positions only follow the numbering rules (booth = row and slot, row 1 on the left with
1001 nearest the entrance, numbers rising away from it), so open scripts/calibrate.html and drag them into place.
Later runs only ADD booths missing from the graph, so your calibration is never overwritten.
The file is edited as text, so its compact one-line-per-entry format stays as it is.
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRAPH = ROOT / "data" / "venue_graph.json"
BOOTHS = ROOT / "data" / "hub_booths.json"
PHOTO = ROOT / "data" / "room-screenshots" / "Hub_Floorplan_Enhanced_300DPI.jpg"
STRAIGHT = ROOT / "data" / "room-screenshots" / "hub-plan-straight.png"

TILT = 8.5  # degrees the phone photo is rotated; the straightened plan has the rows vertical
PHOTO_W, PHOTO_H = 1536, 2048
ROW_X0, ROW_DX = 470, 90        # row 1 centre line and the spacing between rows (straightened frame, fitted to 12 OCR points)
SLOT_Y0, PAIR_DY = 1560, 56     # slot 1 and 2 face each other; each pair of slots is one step up
BOOTH_W, BOOTH_H, SIDE = 30, 46, 17

# centres in the original photo (px), read from the plan labels
THEATERS = {1: (310, 920), 2: (692, 925), 3: (804, 925), 4: (1030, 925), 5: (1258, 929), 6: (730, 1405),
            7: (650, 1405), 8: (597, 761), 9: (665, 761), 10: (510, 516), 11: (440, 516), 12: (760, 1321)}
AREAS = {"ORACLE TV": ((543, 905), "Oracle TV"), "ACE LOUNGE": ((1103, 36), "ACE Lounge"),
         "MULTICLOUD AI DATABASE LOUNGE": ((1232, 180), "Oracle Multicloud AI Database lounge"),
         "OCI SPOTLIGHT": ((1000, 1650), "Oracle Cloud Infrastructure spotlight"),
         "SPORTS SPOTLIGHT": ((970, 1760), "Oracle Sports Spotlight")}
ENTRANCE = (234, 2012)


def straighten(px: float, py: float) -> tuple[float, float]:
    """Photo pixel -> straightened-plan pixel (the same transform as PIL's rotate(TILT, expand=True))."""
    t = math.radians(TILT)
    wn = PHOTO_W * math.cos(t) + PHOTO_H * math.sin(t)
    hn = PHOTO_W * math.sin(t) + PHOTO_H * math.cos(t)
    dx, dy = px - PHOTO_W / 2, py - PHOTO_H / 2
    return wn / 2 + dx * math.cos(t) + dy * math.sin(t), hn / 2 - dx * math.sin(t) + dy * math.cos(t)


def booth_rect(number: str) -> list[float]:
    n = int(number)
    row, slot = n // 1000, n % 100
    pair = (slot + 1) // 2
    x = ROW_X0 + (row - 1) * ROW_DX + (-SIDE if slot % 2 else SIDE)
    y = SLOT_Y0 - (pair - 1) * PAIR_DY
    return [round(x - BOOTH_W / 2), round(y - BOOTH_H / 2), BOOTH_W, BOOTH_H]


def centred(photo_xy: tuple[float, float], w: int, h: int) -> list[float]:
    x, y = straighten(*photo_xy)
    return [round(x - w / 2), round(y - h / 2), w, h]


def line(key: str, value) -> str:
    return f"    {json.dumps(key)}: {json.dumps(value)}"


def add_missing(text: str, booths: dict[str, str]) -> str | None:
    """Append booths that are not on the Hub plan yet (keeps everything already calibrated)."""
    have = json.loads(text)["rooms"]["hub"]
    missing = {n: booth_rect(n) for n in booths if n not in have}
    if not missing:
        return None
    m = re.search(r'^    "hub": \{.*\}(,?)$', text, re.M)
    assert m, "hub rooms line not found"
    add = ", ".join(f'"{n}": {json.dumps(r)}' for n, r in missing.items())
    new = m.group(0)[: m.group(0).rindex("}")] + ", " + add + "}" + m.group(1)
    print(f"Added {len(missing)} booths.")
    return text[: m.start()] + new + text[m.end():]


def main() -> None:
    text = GRAPH.read_text(encoding="utf-8")
    booths = {str(b["booth_number"]): b["name"] for b in json.loads(BOOTHS.read_text(encoding="utf-8"))}
    if '"hub":         {"level": 6' in text:
        out = add_missing(text, booths)
        if out is None:
            print("Hub already in the graph; nothing to add.")
        else:
            GRAPH.write_text(out, encoding="utf-8")
        return

    rooms: dict[str, list[float]] = {}
    labels: dict[str, str] = {}
    for n in range(1, 13):
        rooms[f"T{n}"] = centred(THEATERS[n], 70, 36)
        labels[f"T{n}"] = f"Theater {n}"
    for key, (xy, label) in AREAS.items():
        rooms[key] = centred(xy, 90, 44)
        labels[key] = label
    for number in booths:
        rooms[number] = booth_rect(number)
    aliases = {f"THEATER {n}": [f"T{n}"] for n in range(1, 13)}
    ex, ey = straighten(*ENTRANCE)
    xs = [r[0] for r in rooms.values()] + [r[0] + r[2] for r in rooms.values()]
    ys = [r[1] for r in rooms.values()] + [r[1] + r[3] for r in rooms.values()]
    x0, y0, x1, y1 = round(min(xs) - 40), round(min(ys) - 40), round(max(xs) + 40), round(ey + 40)
    view = [x0, y0, x1 - x0, y1 - y0]
    node_lines = [
        f'    "hub":         {{"level": 6, "x": {round((x0 + x1) / 2)}, "y": {round((y0 + y1) / 2)}, "type": "zone", "rect": {json.dumps(view)}}}',
        f'    "hub_entry":   {{"level": 6, "x": {round(ex)}, "y": {round(ey)}, "type": "junction", "label": "the Hub entrance"}}',
    ]

    def insert_after(pattern: str, addition: str) -> None:
        nonlocal text
        m = re.search(pattern, text)
        assert m, pattern
        text = text[: m.end()] + addition + text[m.end():]

    hub_level = {"name": "Oracle AI World Hub (Level 2)", "view": view, "metersPerPixel": 0.1}
    insert_after(r'    "5": \{"name": "Level 5"[^\n]*\}', ',\n    "6": ' + json.dumps(hub_level))
    insert_after(r'    "l5_elev":[^\n]*\}', ",\n\n" + ",\n".join(node_lines))
    insert_after(r'\["palazzo_ballroom", "l5_esc"\][^\n]*\]', ',\n    ["hall_c", "hub_entry"], ["hub_entry", "hub"]')
    insert_after(r'    "venetian_ballroom": \{"A"[^\n]*\]\}', ",\n" + line("hub", rooms))
    old = '"roomAliases": {"venetian_ballroom": {"HI": ["H", "I"]}}'
    assert old in text
    text = text.replace(old, '"roomAliases": {"venetian_ballroom": {"HI": ["H", "I"]}, "hub": ' + json.dumps(aliases) + '},\n'
                        '  "roomLabels": {"hub": ' + json.dumps(labels) + '},\n  "fixedMeters": {"hall_c|hub_entry": 40}', 1)
    json.loads(text)  # must still be valid JSON before it is written
    GRAPH.write_text(text, encoding="utf-8")

    photo = Path(sys.argv[sys.argv.index("--photo") + 1]) if "--photo" in sys.argv else PHOTO
    try:
        from PIL import Image

        Image.MAX_IMAGE_PIXELS = None
        plan = Image.open(photo).convert("RGB").resize((PHOTO_W, PHOTO_H), Image.LANCZOS)  # the frame all positions use
        plan.rotate(TILT, resample=Image.BICUBIC, expand=True, fillcolor=(255, 255, 255)).save(STRAIGHT)
        print(f"Wrote {STRAIGHT}")
    except OSError as err:  # for example macOS blocking access to a downloaded photo
        print(f"Could not straighten the plan photo ({err}). Pass --photo with a readable copy of the plan")
    print(f"Added the Hub: {len(booths)} booths, 12 theaters, {len(AREAS)} areas; plan view {view}")


if __name__ == "__main__":
    main()
