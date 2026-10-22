"""PNG floor plans (same drawing as app/mapsvg.py) for clients that cannot display SVG, such as ChatGPT."""
from __future__ import annotations

import io
from functools import lru_cache
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .mapsvg import _boards
from .routing import graph
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


def render_level_png(level: int, route: dict[str, Any] | None = None) -> bytes:
    g = graph()
    nodes = g["nodes"]
    vx, vy, vw, vh = g["levels"][str(level)]["view"]
    zones = venue()["zones"]
    ends = {route["from"], route["to"]} if route else set()

    def P(x: float, y: float) -> tuple[float, float]:
        return ((x - vx) * _SS, (y - vy) * _SS)

    img = Image.new("RGB", (vw * _SS, vh * _SS), "#F8F4F0")
    d = ImageDraw.Draw(img)

    def text(x: float, y: float, s: str, size: int, fill: str, halo: bool = False) -> None:
        d.text(P(x, y), s, font=_font(size), fill=fill, anchor="mm",
               stroke_width=5 if halo else 0, stroke_fill="#FFFFFF")

    d.text(P(vx + 24, vy + 44), f"Level {level}", font=_font(38), fill="#481F2B", anchor="lm")
    labels = []
    for zid, n in nodes.items():
        if n["level"] != level or n["type"] != "zone":
            continue
        kind = zones.get(zid, {}).get("kind", "meeting")
        active = zid in ends
        fill = "#F6D4CF" if active else _FILL.get(kind, "#EEEEEE")
        outline, width = (_ACCENT, 3) if active else (_STROKE, 1)
        if "poly" in n:
            pts = [P(x, y) for x, y in n["poly"]]
            d.polygon(pts, fill=fill)
            d.line(pts + [pts[0]], fill=outline, width=width * _SS, joint="curve")
        else:
            x, y, w, h = n["rect"]
            d.rounded_rectangle([P(x, y), P(x + w, y + h)], radius=6 * _SS, fill=fill, outline=outline, width=width * _SS)
        size = 30 if kind == "hall" else 17 if kind == "ballroom" else 20
        labels.append((n["x"], n["y"] + (30 if active else 0), zones.get(zid, {}).get("name", zid), size))
    for a, b in g["edges"]:
        na, nb = nodes[a], nodes[b]
        if na["level"] == level and nb["level"] == level and not (na["type"] == "zone" and nb["type"] == "zone"):
            for p, q in _dashes([P(na["x"], na["y"]), P(nb["x"], nb["y"])], 2 * _SS, 8 * _SS):
                d.line([p, q], fill="#BEAB9B", width=2 * _SS)
    used = set(route.get("path", [])) if route else set()
    for nid, n in nodes.items():
        if n["level"] == level and n["type"] in _KIND:
            marker(d, n["type"], *P(n["x"], n["y"]), nid in used and _boards(route, nid))
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
                cx, cy = P(n["x"], n["y"] - 38)
                r = 20 * _SS
                d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=_ACCENT, outline="#FFFFFF", width=4 * _SS)
                d.text((cx, cy), label, font=_font(22), fill="#FFFFFF", anchor="mm")
    for x, y, name, size in labels:
        text(x, y, name, size, "#2B1A20", halo=True)
    lx, ly = vx + 24, vy + vh - 70
    d.rounded_rectangle([P(lx - 10, ly - 24), P(lx + 240, ly + 56)], radius=10 * _SS, fill="#FFFFFF", outline="#E5D9D0")
    marker(d, "escalator", *P(lx + 14, ly), False)
    d.text(P(lx + 38, ly + 1), "Escalator", font=_font(17), fill="#2B1A20", anchor="lm")
    marker(d, "elevator", *P(lx + 14, ly + 38), False)
    d.text(P(lx + 38, ly + 39), "Elevator (step-free)", font=_font(17), fill="#2B1A20", anchor="lm")
    d.text(P(vx + vw - 16, vy + vh - 16), "Schematic, not to scale. Estimates only.", font=_font(16), fill=_STROKE, anchor="rm")
    img = img.resize((vw, vh), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
