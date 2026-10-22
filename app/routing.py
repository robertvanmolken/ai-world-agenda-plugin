"""Walking router over data/venue_graph.json (Dijkstra) with turn-by-turn steps and per-level polylines.

Distances come from pixel coordinates on the official plans and the metersPerPixel calibration, so all
results are estimates. Pure Python, no third-party dependencies.
"""
from __future__ import annotations

import heapq
import json
import math
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
            steps.append({
                "text": f"Take the {kind} {direction} to Level {cur['level']}",
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


def route(a: str, b: str, step_free: bool = False) -> dict[str, Any] | None:
    """Shortest route between two zone ids (not 'hub'). Minutes exclude the venue buffer.

    step_free avoids escalators and uses elevators only."""
    nodes = graph()["nodes"]
    if a not in nodes or b not in nodes:
        return None
    if a == b:
        level = nodes[a]["level"]
        return {
            "from": a, "to": b, "walkMinutes": venue()["model"]["sameZoneMinutes"], "meters": 0,
            "levels": [level], "steps": [{"text": f"Stay in {_zone_name(a)}", "level": level}],
            "polylines": [{"level": level, "points": [[nodes[a]["x"], nodes[a]["y"]]]}], "path": [a],
            "stepFree": step_free,
        }
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
    return {
        "from": a, "to": b, "walkMinutes": round(minutes, 1), "meters": round(meters),
        "levels": levels, "steps": _steps(path), "polylines": _polylines(path), "path": path,
        "stepFree": step_free,
    }


def _candidates(zone: str) -> list[str]:
    return venue()["hub"]["candidates"] if zone == "hub" else [zone]


def route_range(a: str, b: str, step_free: bool = False) -> dict[str, Any] | None:
    """Route between two zone ids where either may be 'hub' (range over its candidate halls).

    Returns the shortest route plus bestMinutes/worstMinutes over all candidate pairs."""
    routes = [r for x in _candidates(a) for y in _candidates(b) if (r := route(x, y, step_free))]
    if not routes:
        return None
    best = min(routes, key=lambda r: r["walkMinutes"])
    worst = max(routes, key=lambda r: r["walkMinutes"])
    return best | {"bestMinutes": best["walkMinutes"], "worstMinutes": worst["walkMinutes"]}

