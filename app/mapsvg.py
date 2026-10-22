"""Schematic SVG floor plans per level, drawn from data/venue_graph.json, with an optional route overlay."""
from __future__ import annotations

from html import escape
from typing import Any

from .routing import graph, route_range
from .venue import venue

_FILL = {"hall": "#E9DCE0", "ballroom": "#E9DCE0", "meeting": "#DCEBEE"}
_STROKE = "#76686B"
_ACCENT = "#B8321F"
_ICON = {"escalator": "\u21C5", "elevator": "\u21D5"}


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
        name = zones.get(zid, {}).get("name", zid)
        size = 30 if kind == "hall" else 17 if kind == "ballroom" else 20
        labels.append(
            f'<text x="{n["x"]}" y="{n["y"] + (30 if zid in ends else 0)}" font-size="{size}" fill="#2B1A20" '
            f'text-anchor="middle" dominant-baseline="middle" font-weight="600" stroke="#fff" stroke-width="5" '
            f'paint-order="stroke" stroke-linejoin="round">{escape(name)}</text>'
        )
    for a, b in g["edges"]:
        na, nb = nodes[a], nodes[b]
        if na["level"] == level and nb["level"] == level and not (na["type"] == "zone" and nb["type"] == "zone"):
            out.append(f'<line x1="{na["x"]}" y1="{na["y"]}" x2="{nb["x"]}" y2="{nb["y"]}" stroke="#BEAB9B" stroke-width="2" stroke-dasharray="2 8" stroke-linecap="round"/>')
    for nid, n in nodes.items():
        if n["level"] == level and n["type"] in _ICON:
            out.append(
                f'<circle cx="{n["x"]}" cy="{n["y"]}" r="15" fill="#fff" stroke="{_STROKE}" stroke-width="1.5"/>'
                f'<text x="{n["x"]}" y="{n["y"] + 1}" font-size="18" text-anchor="middle" dominant-baseline="middle" fill="{_STROKE}">{_ICON[n["type"]]}</text>'
            )
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
                out.append(
                    f'<circle cx="{n["x"]}" cy="{n["y"] - 38}" r="20" fill="{_ACCENT}" stroke="#fff" stroke-width="4"/>'
                    f'<text x="{n["x"]}" y="{n["y"] - 37}" font-size="22" font-weight="700" fill="#fff" text-anchor="middle" dominant-baseline="middle">{label}</text>'
                )
    out.extend(labels)
    out.append(
        f'<text x="{vx + vw - 16}" y="{vy + vh - 16}" font-size="16" fill="#76686B" text-anchor="end">'
        "Schematic, not to scale. Estimates only.</text>"
    )
    out.append("</svg>")
    return "".join(out)


def render_route(a: str, b: str, level: int | None = None) -> tuple[str, dict[str, Any]] | None:
    """(svg, route) for a walk, defaulting to the first level on the route."""
    r = route_range(a, b)
    if not r:
        return None
    return render_level(level if level is not None else r["levels"][0], r), r
