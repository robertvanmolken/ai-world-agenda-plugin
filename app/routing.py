"""Walking router over data/venue_graph.json (Dijkstra) with turn-by-turn steps and per-level polylines.

Distances come from pixel coordinates on the official plans and the metersPerPixel calibration, so all
results are estimates. Pure Python, no third-party dependencies.
"""
from __future__ import annotations

import heapq
import json
import math
import re
from functools import lru_cache
from typing import Any

from .venue import DATA_DIR, venue


@lru_cache(maxsize=1)
def graph() -> dict[str, Any]:
    return json.loads((DATA_DIR / "venue_graph.json").read_text(encoding="utf-8"))


def _meters(a: dict[str, Any], b: dict[str, Any]) -> float:
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"]) * graph()["metersPerPixel"]


def _px_minutes(a: dict[str, Any], b: dict[str, Any]) -> float:
    return _meters(a, b) / graph()["model"]["walkMetersPerMinute"]


@lru_cache(maxsize=2)
def _adjacency(step_free: bool = False) -> dict[str, list[tuple[str, float, str]]]:
    """node -> [(neighbour, minutes, kind)] where kind is 'walk', 'escalator' or 'elevator'.

    step_free drops every escalator link (the lift wait is added per ride in _path_minutes)."""
    g = graph()
    nodes = g["nodes"]
    adj: dict[str, list[tuple[str, float, str]]] = {n: [] for n in nodes}
    for a, b in g["edges"]:
        m = _px_minutes(nodes[a], nodes[b])
        adj[a].append((b, m, "walk"))
        adj[b].append((a, m, "walk"))
    for a, b, kind in g["links"]:
        if step_free and kind == "escalator":
            continue
        m = g["model"]["escalatorMinutes" if kind == "escalator" else "elevatorMinutes"]
        adj[a].append((b, m, kind))
        adj[b].append((a, m, kind))
    return adj


def room_key(zone: str, room: str | None) -> str | None:
    """Canonical room id inside a zone block ('2204', '2401A', 'HI'), or None when the plan has no such room."""
    rooms = graph().get("rooms", {}).get(zone)
    if not rooms or not room:
        return None
    k = str(room).strip().upper().split("/")[0].strip()
    if k in rooms or k in graph().get("roomAliases", {}).get(zone, {}):
        return k
    return None


def room_rect(zone: str, room: str | None) -> list[float] | None:
    """[x, y, w, h] of a room on the plan. Aliases such as 'HI' (H and I together) give the union."""
    k = room_key(zone, room)
    if not k:
        return None
    rooms = graph()["rooms"][zone]
    parts = graph().get("roomAliases", {}).get(zone, {}).get(k, [k])
    rects = [rooms[p] for p in parts]
    x0, y0 = min(r[0] for r in rects), min(r[1] for r in rects)
    x1, y1 = max(r[0] + r[2] for r in rects), max(r[1] + r[3] for r in rects)
    return [x0, y0, x1 - x0, y1 - y0]


def room_parts(zone: str, room: str | None) -> list[str]:
    """Room names to highlight for a key ('HI' -> ['H', 'I'])."""
    return graph().get("roomAliases", {}).get(zone, {}).get(room, [room]) if room else []


def place_room(text: str, zone: str | None) -> str | None:
    """Pull a room out of free text such as 'Titian 2204', 'Galileo 1001, Level 1' or 'Venetian Ballroom HI'."""
    if not zone or zone not in graph().get("rooms", {}):
        return None
    for tok in re.findall(r"\b\d{3,4}[A-Za-z]?\b", text or ""):
        if room_key(zone, tok):
            return room_key(zone, tok)
    m = re.search(r"ballroom[\s,]*(?:section\s+)?([A-La-l]{1,2})\b", text or "", re.I)
    return room_key(zone, m.group(1)) if m else None


def room_name(zone: str, room: str | None) -> str:
    base = _zone_name(zone)
    if not room:
        return base
    return f"{base} section {room}" if zone == "venetian_ballroom" else f"{base} {room}"


def has_zone(zone: str) -> bool:
    return zone in graph()["nodes"]


def shortest_path(a: str, b: str, step_free: bool = False) -> tuple[float, list[str]] | None:
    """(minutes, node path) between two graph nodes, or None when unreachable."""
    adj = _adjacency(step_free)
    if a not in adj or b not in adj:
        return None
    dist = {a: 0.0}
    prev: dict[str, str] = {}
    heap = [(0.0, a)]
    while heap:
        d, n = heapq.heappop(heap)
        if n == b:
            break
        if d > dist.get(n, math.inf):
            continue
        for m, w, _ in adj[n]:
            nd = d + w
            if nd < dist.get(m, math.inf):
                dist[m] = nd
                prev[m] = n
                heapq.heappush(heap, (nd, m))
    if b not in dist:
        return None
    path = [b]
    while path[-1] != a:
        path.append(prev[path[-1]])
    return dist[b], path[::-1]


def _zone_name(zone: str) -> str:
    z = venue()["zones"].get(zone)
    return z["name"] if z else zone


def _link_kind(a: str, b: str) -> str | None:
    for x, y, kind in graph()["links"]:
        if {x, y} == {a, b}:
            return kind
    return None


def _path_minutes(path: list[str]) -> float:
    """Minutes for a path. A lift ride through several levels waits once: the first level costs
    elevatorMinutes (wait plus ride) and each further level elevatorExtraLevelMinutes."""
    nodes, model = graph()["nodes"], graph()["model"]
    total, in_lift = 0.0, False
    for i in range(1, len(path)):
        kind = _link_kind(path[i - 1], path[i])
        if kind == "elevator":
            total += model["elevatorExtraLevelMinutes"] if in_lift else model["elevatorMinutes"]
            in_lift = True
        else:
            total += _px_minutes(nodes[path[i - 1]], nodes[path[i]]) if not kind else model["escalatorMinutes"]
            in_lift = False
    return total


def _steps(path: list[str]) -> list[dict[str, Any]]:
    nodes = graph()["nodes"]
    steps: list[dict[str, Any]] = [{"text": f"Leave {_zone_name(path[0])}", "level": nodes[path[0]]["level"]}]
    meters = 0.0
    for i in range(1, len(path)):
        prev, cur = nodes[path[i - 1]], nodes[path[i]]
        kind = _link_kind(path[i - 1], path[i])
        if kind:
            if meters >= 5:
                steps[-1]["meters"] = round(meters)
            meters = 0.0
            direction = "up" if cur["level"] > prev["level"] else "down"
            what = "escalator or stairs" if kind == "escalator" and (prev.get("stairs") or cur.get("stairs")) else kind
            steps.append({
                "text": f"Take the {what} {direction} to Level {cur['level']}",
                "level": cur["level"], "levelChange": True,
            })
            continue
        meters += _meters(prev, cur)
        last = i == len(path) - 1
        label = cur.get("label")
        # name an escalator or elevator only when the route actually takes it, not when it walks past
        boarding = not last and cur["type"] in ("escalator", "elevator") and _link_kind(path[i], path[i + 1])
        if last or (label and (cur["type"] == "junction" or boarding)):
            text = f"Arrive at {_zone_name(path[i])}" if last else f"Walk to {label}"
            steps.append({"text": text, "level": cur["level"], "meters": round(meters)})
            meters = 0.0
    return steps


def _polylines(path: list[str]) -> list[dict[str, Any]]:
    nodes = graph()["nodes"]
    out: list[dict[str, Any]] = []
    for n in path:
        node = nodes[n]
        if not out or out[-1]["level"] != node["level"]:
            out.append({"level": node["level"], "points": []})
        out[-1]["points"].append([node["x"], node["y"]])
    return out


def _center(rect: list[float]) -> tuple[float, float]:
    return rect[0] + rect[2] / 2, rect[1] + rect[3] / 2


def _apply_rooms(r: dict[str, Any], a: str, b: str, room_a: str | None, room_b: str | None) -> dict[str, Any]:
    """Start and end the walk at the room centres instead of the block centres."""
    ra, rb = room_rect(a, room_a), room_rect(b, room_b)
    if not ra and not rb:
        return r
    mpp, speed = graph()["metersPerPixel"], graph()["model"]["walkMetersPerMinute"]
    steps, polys = r["steps"], r["polylines"]
    if a == b:
        if not (ra and rb) or room_a == room_b:
            return r
        (x1, y1), (x2, y2) = _center(ra), _center(rb)
        m = math.hypot(x1 - x2, y1 - y2) * mpp
        level = graph()["nodes"][a]["level"]
        return r | {
            "meters": round(m), "walkMinutes": round(max(r["walkMinutes"], m / speed), 1),
            "steps": [{"text": f"Walk from {room_name(a, room_a)} to {room_name(b, room_b)}", "level": level, "meters": round(m)}],
            "polylines": [{"level": level, "points": [[x1, y1], [x2, y2]]}], "fromRoom": room_a, "toRoom": room_b,
        }
    delta = 0.0

    def seg(points: list[list[float]], i: int, j: int) -> float:
        return math.hypot(points[i][0] - points[j][0], points[i][1] - points[j][1])

    if ra and len(polys[0]["points"]) >= 2:
        pts = polys[0]["points"]
        old = seg(pts, 0, 1)
        pts[0] = list(_center(ra))
        d = (seg(pts, 0, 1) - old) * mpp
        delta += d
        steps[0]["text"] = f"Leave {room_name(a, room_a)}"
        first = next((s for s in steps[1:] if "meters" in s), None)
        if first:
            first["meters"] = max(0, round(first["meters"] + d))
    if rb and len(polys[-1]["points"]) >= 2:
        pts = polys[-1]["points"]
        old = seg(pts, -2, -1)
        pts[-1] = list(_center(rb))
        d = (seg(pts, -2, -1) - old) * mpp
        delta += d
        steps[-1]["text"] = f"Arrive at {room_name(b, room_b)}"
        steps[-1]["meters"] = max(0, round(steps[-1].get("meters", 0) + d))
    return r | {
        "meters": max(0, round(r["meters"] + delta)),
        "walkMinutes": round(max(0.1, r["walkMinutes"] + delta / speed), 1),
        "fromRoom": room_a if ra else None, "toRoom": room_b if rb else None,
    }


def route(a: str, b: str, step_free: bool = False, room_a: str | None = None, room_b: str | None = None) -> dict[str, Any] | None:
    """Shortest route between two zone ids (not 'hub'). Minutes exclude the venue buffer.

    step_free avoids escalators and uses elevators only. room_a / room_b (for example '2204') end the
    walk at that room on the plan instead of the middle of the block."""
    nodes = graph()["nodes"]
    if a not in nodes or b not in nodes:
        return None
    if a == b:
        level = nodes[a]["level"]
        return _apply_rooms({
            "from": a, "to": b, "walkMinutes": venue()["model"]["sameZoneMinutes"], "meters": 0,
            "levels": [level], "steps": [{"text": f"Stay in {_zone_name(a)}", "level": level}],
            "polylines": [{"level": level, "points": [[nodes[a]["x"], nodes[a]["y"]]]}], "path": [a],
            "stepFree": step_free,
        }, a, b, room_key(a, room_a), room_key(b, room_b))
    found = shortest_path(a, b, step_free)
    if not found:
        return None
    minutes, path = found
    minutes = _path_minutes(path)
    if not step_free:
        # the default route may also use lifts, so it is never slower than the step-free one
        alt = shortest_path(a, b, True)
        if alt and _path_minutes(alt[1]) < minutes:
            minutes, path = _path_minutes(alt[1]), alt[1]
    meters = sum(
        _meters(nodes[path[i - 1]], nodes[path[i]])
        for i in range(1, len(path)) if not _link_kind(path[i - 1], path[i])
    )
    levels: list[int] = []
    for n in path:
        lv = nodes[n]["level"]
        if not levels or levels[-1] != lv:
            levels.append(lv)
    return _apply_rooms({
        "from": a, "to": b, "walkMinutes": round(minutes, 1), "meters": round(meters),
        "levels": levels, "steps": _steps(path), "polylines": _polylines(path), "path": path,
        "stepFree": step_free,
    }, a, b, room_key(a, room_a), room_key(b, room_b))


def _candidates(zone: str) -> list[str]:
    return venue()["hub"]["candidates"] if zone == "hub" else [zone]


def route_range(a: str, b: str, step_free: bool = False, room_a: str | None = None, room_b: str | None = None) -> dict[str, Any] | None:
    """Route between two zone ids where either may be 'hub' (range over its candidate halls).

    Returns the shortest route plus bestMinutes/worstMinutes over all candidate pairs."""
    routes = [r for x in _candidates(a) for y in _candidates(b) if (r := route(x, y, step_free, room_a, room_b))]
    if not routes:
        return None
    best = min(routes, key=lambda r: r["walkMinutes"])
    worst = max(routes, key=lambda r: r["walkMinutes"])
    return best | {"bestMinutes": best["walkMinutes"], "worstMinutes": worst["walkMinutes"]}

