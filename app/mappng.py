"""PNG floor plans (same drawing as app/mapsvg.py) for clients that cannot display SVG, such as ChatGPT."""
from __future__ import annotations

import io
from functools import lru_cache
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .mapsvg import _boards
import math

from .routing import graph, hub_estimated, hub_rotation, hub_view, room_parts, room_rect
from .venue import venue

_FILL = {"hall": "#E9DCE0", "ballroom": "#E9DCE0", "meeting": "#DCEBEE"}
_STROKE = "#76686B"
_ACCENT = "#B8321F"
_SS = 2  # supersampling factor, the result is scaled back down for smooth edges
_KIND = ("escalator", "elevator")
_ELEV = "#2F6DB5"


@lru_cache(maxsize=16)
def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=size * _SS)


def _dashes(points: list[tuple[float, float]], on: float, off: float) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    out, carry, drawing = [], 0.0, True
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        if not length:
            continue
        pos = 0.0
        while pos < length:
            span = (on if drawing else off) - carry
            end = min(length, pos + span)
            if drawing:
                a, b = pos / length, end / length
                out.append(((x1 + (x2 - x1) * a, y1 + (y2 - y1) * a), (x1 + (x2 - x1) * b, y1 + (y2 - y1) * b)))
            if pos + span <= length:
                drawing, carry = not drawing, 0.0
            else:
                carry += end - pos
            pos = end
    return out


def marker(d: ImageDraw.ImageDraw, kind: str, cx: float, cy: float, used: bool) -> None:
    """Escalator: round, two arrows side by side. Elevator: blue rounded square, one up and one down arrow."""
    ring = _ACCENT if used else (_ELEV if kind == "elevator" else _STROKE)
    fill = "#FDECE8" if used else "#FFFFFF"
    w = int((3 if used else 1.8) * _SS)
    r = 15 * _SS
    if kind == "elevator":
        d.rounded_rectangle([cx - r, cy - r, cx + r, cy + r], radius=7 * _SS, fill=fill, outline=ring, width=w)
        for sign in (-1, 1):
            tip, base = cy + sign * 10 * _SS, cy + sign * 2 * _SS
            d.polygon([(cx, tip), (cx - 5.5 * _SS, base), (cx + 5.5 * _SS, base)], fill=ring)
    else:
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill, outline=ring, width=w)
        d.polygon([(cx - 6 * _SS, cy - 9 * _SS), (cx - 11 * _SS, cy + 5 * _SS), (cx - 1 * _SS, cy + 5 * _SS)], fill=ring)
        d.polygon([(cx + 6 * _SS, cy + 9 * _SS), (cx + 1 * _SS, cy - 5 * _SS), (cx + 11 * _SS, cy - 5 * _SS)], fill=ring)


def stairs(d: ImageDraw.ImageDraw, x: float, y: float, color: str) -> None:
    pts = [(x + 20, y + 8)]
    for _ in range(4):
        px, py = pts[-1]
        pts += [(px + 6, py), (px + 6, py - 5)]
    d.line([(px * _SS, py * _SS) for px, py in pts], fill=color, width=3 * _SS, joint="curve")


def render_level_png(level: int, route: dict[str, Any] | None = None) -> bytes:
    g = graph()
    nodes = g["nodes"]
    vx, vy, vw, vh = hub_view(route) if level == 6 else g["levels"][str(level)]["view"]
    zones = venue()["zones"]
    ends = {route["from"], route["to"]} if route else set()

    def P(x: float, y: float) -> tuple[float, float]:
        return ((x - vx) * _SS, (y - vy) * _SS)

    img = Image.new("RGB", (vw * _SS, vh * _SS), "#F8F4F0")
    d = ImageDraw.Draw(img)

    def text(x: float, y: float, s: str, size: int, fill: str, halo: bool = False) -> None:
        d.text(P(x, y), s, font=_font(size), fill=fill, anchor="mm",
               stroke_width=5 if halo else 0, stroke_fill="#FFFFFF")

    title = g["levels"][str(level)].get("name") if level > 5 else f"Level {level}"
    d.text(P(vx + 24, vy + 44), title or f"Level {level}", font=_font(38), fill="#481F2B", anchor="lm")
    labels = []
    for zid, n in nodes.items():
        if n["level"] != level or n["type"] != "zone":
            continue
        kind = zones.get(zid, {}).get("kind", "meeting")
        active = zid in ends
        fill = "#F6D4CF" if active else _FILL.get(kind, "#EEEEEE")
        outline, width = (_ACCENT, 3) if active else (_STROKE, 1)
        if zid == "hub" and g["levels"]["6"].get("outline"):
            pts = [P(x, y) for x, y in g["levels"]["6"]["outline"]]
            d.polygon(pts, fill="#FBF2EE")
            d.line(pts + [pts[0]], fill="#BEAB9B", width=3 * _SS, joint="curve")
        elif "poly" in n:
            pts = [P(x, y) for x, y in n["poly"]]
            d.polygon(pts, fill=fill)
            d.line(pts + [pts[0]], fill=outline, width=width * _SS, joint="curve")
        else:
            x, y, w, h = n["rect"]
            d.rounded_rectangle([P(x, y), P(x + w, y + h)], radius=6 * _SS, fill=fill, outline=outline, width=width * _SS)
        size = 30 if kind == "hall" else 17 if kind == "ballroom" else 20
        rooms = g.get("rooms", {}).get(zid)
        hi: set[str] = set()
        if rooms and route:
            if zid == route["from"]:
                hi |= set(room_parts(zid, route.get("fromRoom")))
            if zid == route["to"]:
                hi |= set(room_parts(zid, route.get("toRoom")))
        hub_labels = g.get("roomLabels", {}).get("hub", {}) if zid == "hub" else {}
        for name, (rx, ry, rw, rh) in (rooms or {}).items():
            on = name in hi
            big = name in hub_labels
            fill = "#F6D4CF" if on else ("#DCEBEE" if big else "#F7FBFC")
            rot = hub_rotation(name) if zid == "hub" else 0
            ocx, ocy = rx + rw / 2, ry + rh / 2
            a_ = math.radians(rot)
            corners = [(ocx + (dx * math.cos(a_) - dy * math.sin(a_)), ocy + (dx * math.sin(a_) + dy * math.cos(a_)))
                       for dx, dy in ((-rw / 2, -rh / 2), (rw / 2, -rh / 2), (rw / 2, rh / 2), (-rw / 2, rh / 2))]
            border = int((3 if on else 1.4 if big else .9) * _SS) or 1
            d.polygon([P(*c) for c in corners], fill=fill)
            edge = [P(*c) for c in corners]
            if zid == "hub" and hub_estimated(name):  # estimated places: dashed outline
                for i in range(4):
                    for p, q in _dashes([edge[i], edge[(i + 1) % 4]], 3 * _SS, 2 * _SS):
                        d.line([p, q], fill=_ACCENT if on else "#9DB4BA", width=border)
            else:
                d.line(edge + [edge[0]], fill=_ACCENT if on else "#9DB4BA", width=border)
            if on:
                if zid == "hub":
                    from .hub import booths

                    name = hub_labels.get(name) or f"{name} {booths().get(name, '')}".strip()
                d.text(P(rx + rw / 2, ry - (16 if zid == "hub" else 14)), name, font=_font(26 if zid == "hub" else 22), fill=_ACCENT,
                       anchor="mm", stroke_width=6 if zid == "hub" else 5, stroke_fill="#FFFFFF")
            elif not hi and (zid != "hub" or big or max(rw, rh) >= 20):
                text_ = name
                if big and not name.startswith("T"):
                    text_ = hub_labels[name].split(":")[0] if name.startswith("Z") else hub_labels[name]
                d.text(P(rx + rw / 2, ry + rh / 2), text_, font=_font(14 if big else 12 if zid == "venetian_ballroom" else 7 if zid == "hub" and min(rw, rh) < 25 else 9),
                       fill="#31575F" if big else "#4A6168", anchor="mm")
        zone_name = venue()["hub"]["name"] if zid == "hub" else zones.get(zid, {}).get("name", zid)
        if zid == "hub":
            continue
        labels.append((n["x"], n["rect"][1] - 12 if rooms else n["y"] + (30 if active else 0), zone_name, size))
    for a, b in g["edges"]:
        na, nb = nodes[a], nodes[b]
        if na["level"] == level and nb["level"] == level and not (na["type"] == "zone" and nb["type"] == "zone"):
            for p, q in _dashes([P(na["x"], na["y"]), P(nb["x"], nb["y"])], 2 * _SS, 8 * _SS):
                d.line([p, q], fill="#BEAB9B", width=2 * _SS)
    used = set(route.get("path", [])) if route else set()
    for nid, n in nodes.items():
        if n["level"] == level and n["type"] in _KIND:
            hot = nid in used and _boards(route, nid)
            marker(d, n["type"], *P(n["x"], n["y"]), hot)
            if n.get("stairs"):
                stairs(d, n["x"] - vx, n["y"] - vy, _ACCENT if hot else _STROKE)
    if route:
        for pl in route.get("polylines", []):
            if pl["level"] != level or len(pl["points"]) < 2:
                continue
            pts = [P(x, y) for x, y in pl["points"]]
            d.line(pts, fill="#FFFFFF", width=12 * _SS, joint="curve")
            for p, q in _dashes(pts, 14 * _SS, 10 * _SS):
                d.line([p, q], fill=_ACCENT, width=7 * _SS)
        for key, label in (("from", "A"), ("to", "B")):
            n = nodes.get(route[key])
            if n and n["level"] == level:
                rect = room_rect(route[key], route.get("fromRoom" if key == "from" else "toRoom"))
                px, py = (rect[0] + rect[2] / 2, rect[1] + rect[3] / 2) if rect else (n["x"], n["y"])
                cx, cy = P(px, py - 38)
                r = 20 * _SS
                d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=_ACCENT, outline="#FFFFFF", width=4 * _SS)
                d.text((cx, cy), label, font=_font(22), fill="#FFFFFF", anchor="mm")
    for x, y, name, size in labels:
        text(x, y, name, size, "#2B1A20", halo=True)
    lx, ly = vx + 24, vy + vh - 70
    d.rounded_rectangle([P(lx - 10, ly - 24), P(lx + 260, ly + 94)], radius=10 * _SS, fill="#FFFFFF", outline="#E5D9D0")
    marker(d, "escalator", *P(lx + 14, ly), False)
    d.text(P(lx + 38, ly + 1), "Escalator", font=_font(17), fill="#2B1A20", anchor="lm")
    marker(d, "elevator", *P(lx + 14, ly + 38), False)
    d.text(P(lx + 38, ly + 39), "Elevator (step-free)", font=_font(17), fill="#2B1A20", anchor="lm")
    stairs(d, lx - 6 - vx, ly + 66 - vy, _STROKE)
    d.text(P(lx + 38, ly + 77), "Stairs next to escalator", font=_font(17), fill="#2B1A20", anchor="lm")
    d.text(P(vx + vw - 16, vy + vh - 16), "Schematic, not to scale. Estimates only.", font=_font(16), fill=_STROKE, anchor="rm")
    img = img.resize((vw, vh), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
