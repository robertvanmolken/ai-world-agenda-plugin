"""Schematic SVG floor plans per level, drawn from data/venue_graph.json, with an optional route overlay."""
from __future__ import annotations

from html import escape
from typing import Any

from .routing import graph, room_parts, room_rect, route_range
from .venue import venue

_FILL = {"hall": "#E9DCE0", "ballroom": "#E9DCE0", "meeting": "#DCEBEE"}
_STROKE = "#76686B"
_ACCENT = "#B8321F"
_ICON = ("escalator", "elevator")
_ELEV = "#2F6DB5"  # elevators are blue, escalators use the plan colour


def _marker(kind: str, x: float, y: float, used: bool) -> str:
    """Escalator: round, two arrows side by side. Elevator: blue rounded square, one up and one down arrow."""
    ring = _ACCENT if used else (_ELEV if kind == "elevator" else _STROKE)
    fill = "#FDECE8" if used else "#fff"
    w = 3 if used else 1.8
    glyph = _ACCENT if used else ring
    if kind == "elevator":
        body = f'<rect x="{x - 15}" y="{y - 15}" width="30" height="30" rx="7" fill="{fill}" stroke="{ring}" stroke-width="{w}"/>'
        arrows = (f'<path d="M{x} {y - 10} l-5.5 8 h11 z M{x} {y + 10} l-5.5 -8 h11 z" fill="{glyph}"/>')
    else:
        body = f'<circle cx="{x}" cy="{y}" r="15" fill="{fill}" stroke="{ring}" stroke-width="{w}"/>'
        arrows = (f'<path d="M{x - 6} {y - 9} l-5 14 h10 z M{x + 6} {y + 9} l-5 -14 h10 z" fill="{glyph}"/>')
    return body + arrows


def _legend(vx: int, vy: int, vw: int, vh: int) -> str:
    x, y = vx + 24, vy + vh - 70
    return (
        f'<rect x="{x - 10}" y="{y - 24}" width="250" height="80" rx="10" fill="#fff" fill-opacity=".85" stroke="#E5D9D0"/>'
        + _marker("escalator", x + 14, y, False) + f'<text x="{x + 38}" y="{y + 1}" font-size="17" fill="#2B1A20" dominant-baseline="middle">Escalator</text>'
        + _marker("elevator", x + 14, y + 38, False) + f'<text x="{x + 38}" y="{y + 39}" font-size="17" fill="#2B1A20" dominant-baseline="middle">Elevator (step-free)</text>'
    )


def _rooms_svg(zone: str, hi: set[str]) -> str:
    out = []
    for name, (x, y, w, h) in graph().get("rooms", {}).get(zone, {}).items():
        on = name in hi
        out.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="2" fill="{"#F6D4CF" if on else "#F7FBFC"}" '
            f'stroke="{_ACCENT if on else "#9DB4BA"}" stroke-width="{1.6 if on else .8}"/>'
            f'<text x="{x + w / 2}" y="{y + h / 2}" font-size="{12 if zone == "venetian_ballroom" else 8.5}" '
            f'fill="{_ACCENT if on else "#4A6168"}" text-anchor="middle" dominant-baseline="middle" '
            f'font-weight="{700 if on else 500}">{escape(name)}</text>'
        )
    return "".join(out)


def _end_point(route: dict[str, Any], key: str, node: dict[str, Any]) -> tuple[float, float]:
    rect = room_rect(route[key], route.get("fromRoom" if key == "from" else "toRoom"))
    return (rect[0] + rect[2] / 2, rect[1] + rect[3] / 2) if rect else (node["x"], node["y"])


def levels() -> list[int]:
    return sorted(int(k) for k in graph()["levels"])


def _shape(node: dict[str, Any], kind: str, active: str) -> str:
    fill = "#F6D4CF" if active else _FILL.get(kind, "#EEE")
    stroke = _ACCENT if active else _STROKE
    width = 3 if active else 1.2
    attrs = f'fill="{fill}" stroke="{stroke}" stroke-width="{width}" stroke-linejoin="round"'
    if "poly" in node:
        pts = " ".join(f"{x},{y}" for x, y in node["poly"])
        return f'<polygon points="{pts}" {attrs}/>'
    x, y, w, h = node["rect"]
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" {attrs}/>'


def _boards(route: dict[str, Any], node: str) -> bool:
    """True when the route changes level at this escalator or elevator (not when it only walks past)."""
    path = route.get("path", [])
    nodes = graph()["nodes"]
    return any(
        p == node and ((i > 0 and nodes[path[i - 1]]["level"] != nodes[p]["level"])
                       or (i + 1 < len(path) and nodes[path[i + 1]]["level"] != nodes[p]["level"]))
        for i, p in enumerate(path)
    )


def render_level(level: int, route: dict[str, Any] | None = None, width: int | None = None) -> str:
    """SVG for one level. route is a dict from routing.route/route_range (polylines, from, to)."""
    g = graph()
    nodes = g["nodes"]
    vx, vy, vw, vh = g["levels"][str(level)]["view"]
    zones = venue()["zones"]
    ends = {route["from"], route["to"]} if route else set()
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vx} {vy} {vw} {vh}" role="img" '
        f'aria-label="Schematic plan of Level {level}"' + (f' width="{width}"' if width else "") + ">",
        '<style>text{font-family:"Plus Jakarta Sans",Arial,sans-serif}'
        "@keyframes dash{to{stroke-dashoffset:-48}}.route{animation:dash 1.2s linear infinite}</style>",
        f'<rect x="{vx}" y="{vy}" width="{vw}" height="{vh}" fill="#F8F4F0"/>',
        f'<text x="{vx + 24}" y="{vy + 44}" font-size="38" fill="#481F2B" font-weight="700">Level {level}</text>',
    ]
    labels: list[str] = []
    for zid, n in nodes.items():
        if n["level"] != level or n["type"] != "zone":
            continue
        kind = zones.get(zid, {}).get("kind", "meeting")
        out.append(_shape(n, kind, zid if zid in ends else ""))
        has_rooms = zid in graph().get("rooms", {})
        hi: set[str] = set()
        if route and has_rooms:
            if zid == route["from"]:
                hi |= set(room_parts(zid, route.get("fromRoom")))
            if zid == route["to"]:
                hi |= set(room_parts(zid, route.get("toRoom")))
            out.append(_rooms_svg(zid, hi))
        elif has_rooms:
            out.append(_rooms_svg(zid, hi))
        name = zones.get(zid, {}).get("name", zid)
        size = 30 if kind == "hall" else 17 if kind == "ballroom" else 20
        label_y = n["rect"][1] - 12 if has_rooms else n["y"] + (30 if zid in ends else 0)
        labels.append(
            f'<text x="{n["x"]}" y="{label_y}" font-size="{size}" fill="#2B1A20" '
            f'text-anchor="middle" dominant-baseline="middle" font-weight="600" stroke="#fff" stroke-width="5" '
            f'paint-order="stroke" stroke-linejoin="round">{escape(name)}</text>'
        )
    for a, b in g["edges"]:
        na, nb = nodes[a], nodes[b]
        if na["level"] == level and nb["level"] == level and not (na["type"] == "zone" and nb["type"] == "zone"):
            out.append(f'<line x1="{na["x"]}" y1="{na["y"]}" x2="{nb["x"]}" y2="{nb["y"]}" stroke="#BEAB9B" stroke-width="2" stroke-dasharray="2 8" stroke-linecap="round"/>')
    used = set(route.get("path", [])) if route else set()
    for nid, n in nodes.items():
        if n["level"] == level and n["type"] in _ICON:
            out.append(_marker(n["type"], n["x"], n["y"], nid in used and _boards(route, nid)))
    if route:
        for pl in route.get("polylines", []):
            if pl["level"] != level or len(pl["points"]) < 2:
                continue
            pts = " ".join(f"{x},{y}" for x, y in pl["points"])
            out.append(f'<polyline points="{pts}" fill="none" stroke="#fff" stroke-width="12" stroke-linecap="round" stroke-linejoin="round"/>')
            out.append(f'<polyline class="route" points="{pts}" fill="none" stroke="{_ACCENT}" stroke-width="7" stroke-dasharray="14 10" stroke-linecap="round" stroke-linejoin="round"/>')
        for key, label in (("from", "A"), ("to", "B")):
            n = nodes.get(route[key])
            if n and n["level"] == level:
                px, py = _end_point(route, key, n)
                out.append(
                    f'<circle cx="{px}" cy="{py - 38}" r="20" fill="{_ACCENT}" stroke="#fff" stroke-width="4"/>'
                    f'<text x="{px}" y="{py - 37}" font-size="22" font-weight="700" fill="#fff" text-anchor="middle" dominant-baseline="middle">{label}</text>'
                )
    out.extend(labels)
    out.append(_legend(vx, vy, vw, vh))
    out.append(
        f'<text x="{vx + vw - 16}" y="{vy + vh - 16}" font-size="16" fill="#76686B" text-anchor="end">'
        "Schematic, not to scale. Estimates only.</text>"
    )
    out.append("</svg>")
    return "".join(out)


def render_route(a: str, b: str, level: int | None = None, step_free: bool = False) -> tuple[str, dict[str, Any]] | None:
    """(svg, route) for a walk, defaulting to the first level on the route."""
    r = route_range(a, b, step_free)
    if not r:
        return None
    return render_level(level if level is not None else r["levels"][0], r), r
