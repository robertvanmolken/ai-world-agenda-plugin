"""MCP server (Claude, ChatGPT and any other MCP client) plus the legacy REST routes.

Run modes:
  python -m app.mcp_server            -> stdio (Claude Desktop / Claude Code local)
  uvicorn app.asgi:app                -> Streamable HTTP at /mcp (+ REST routes)
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, ImageContent, Icon, TextContent, ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .catalog import find_conflicts, get_by_code, load_catalog, mark_early, mark_paid, optimize_agenda, search_sessions
from .planner import plan_day
from .routing import place_room
from .venue import assess_transition, check_move, load_rooms, merge_rooms, resolve_place, route_details, venue

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = Path(os.environ.get("AI_WORLD_DATA", ROOT / "data" / "sessions.json"))

PUBLIC_URL = os.environ.get("PUBLIC_URL", "https://aiworld.exoblock.it").rstrip("/")

_catalog: dict[str, Any] | None = None


def catalog() -> dict[str, Any]:
    global _catalog
    if _catalog is None:
        _catalog = load_catalog(DATA_FILE)
        merge_rooms(_catalog["sessions"], load_rooms())
        mark_paid(_catalog["sessions"])
        mark_early(_catalog["sessions"])
    return _catalog


def sessions() -> list[dict[str, Any]]:
    return catalog()["sessions"]


def _security() -> TransportSecuritySettings:
    """Host/origin validation. ALLOWED_HOSTS is a comma separated list, e.g. 'my-app.onrender.com'.
    Unset (default) disables DNS-rebinding protection, which is fine for a public read-only API."""
    hosts = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()]
    if not hosts:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts + [f"{h}:*" for h in hosts],
        allowed_origins=["*"],
    )


DISCLAIMER = (
    "Unofficial snapshot of the Oracle AI World 2026 session catalog (captured 2026-10-27; days that were already over keep the earlier capture). Rooms come from the "
    "catalog and walking times are rough estimates, so verify times, rooms and availability in the official "
    "Oracle catalog and the event app before relying on them. Always show this disclaimer to the user."
)


def absolute_maps(result: dict[str, Any]) -> dict[str, Any]:
    """Make map URLs in routeDetail absolute so MCP clients can open them."""
    d = result.get("routeDetail")
    if d and d.get("mapUrls"):
        # PNG first: ChatGPT cannot show SVG. The SVG stays available as svgUrl.
        d = {**d, "mapUrls": [{"level": m["level"], "label": m.get("label"), "url": PUBLIC_URL + m["pngUrl"], "svgUrl": PUBLIC_URL + m["url"]}
                              for m in d["mapUrls"]],
             # ChatGPT often cannot embed images; this page shows steps and all maps and opens when clicked.
             "pageUrl": PUBLIC_URL + d["pageUrl"]}
        d.pop("polylines", None)
        result = {**result, "routeDetail": d}
    return result


def with_map_images(result: dict[str, Any]) -> CallToolResult:
    """Tool result with the JSON as structuredContent, a text summary, and one raw-base64 PNG image block per level.

    Many chat clients never fetch image URLs, but they do show image content blocks."""
    import base64
    from urllib.parse import parse_qs, urlsplit

    from .mappng import render_level_png
    from .routing import route_range

    text = json.dumps(result, ensure_ascii=False)
    blocks: list[Any] = []
    d = result.get("routeDetail") or {}
    for m in d.get("mapUrls", []):
        q = {k: v[0] for k, v in parse_qs(urlsplit(m["url"]).query).items()}
        r = route_range(q.get("from", ""), q.get("to", ""), q.get("stepFree") == "1", q.get("fromRoom"), q.get("toRoom"))
        if r:
            png = render_level_png(int(q["level"]), r)
            blocks.append(ImageContent(type="image", mimeType="image/png", data=base64.b64encode(png).decode("ascii")))
    summary = (f"Walking route maps follow ({len(blocks)} image(s), one per level). Show them to the user and also give "
               f"the link {d.get('pageUrl', '')}. Data: ")
    return CallToolResult(content=[TextContent(type="text", text=summary + text), *blocks], structuredContent=result)


def with_disclaimer(result: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a tool result with the disclaimer attached."""
    return {**result, "disclaimer": DISCLAIMER}


mcp = FastMCP(
    "Oracle AI World 2026 Agenda Assistant",
    instructions=(
        "Search the Oracle AI World 2026 session catalog (an unofficial snapshot), detect schedule "
        "conflicts and propose a personal agenda. Dates are ISO (YYYY-MM-DD), times are 24h HH:MM. "
        "Verify critical details in the official Oracle catalog. Every tool result has a 'disclaimer' field: "
        "always include it in your answer. Sessions with paid=true need a separate paid registration through My Account: say so whenever you recommend one."
    ),
    website_url=PUBLIC_URL,
    icons=[
        Icon(src=f"{PUBLIC_URL}/icon.png", mimeType="image/png", sizes=["512x512"]),
        Icon(src=f"{PUBLIC_URL}/icon-192.png", mimeType="image/png", sizes=["192x192"]),
    ],
    stateless_http=True,
    json_response=True,
    streamable_http_path="/mcp",
    host=os.environ.get("HOST", "0.0.0.0"),
    port=int(os.environ.get("PORT", "8787")),
    transport_security=_security(),
)

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

# Inline route-map widget (MCP Apps). Tools stay useful without it: they still return image blocks and JSON.
ROUTE_WIDGET_URI = "ui://widget/route-map.html"
ROUTE_WIDGET_MIME = "text/html;profile=mcp-app"
ROUTE_WIDGET_TOOL_META = {"ui": {"resourceUri": ROUTE_WIDGET_URI}, "openai/outputTemplate": ROUTE_WIDGET_URI}


@mcp.resource(
    ROUTE_WIDGET_URI, name="route-map-widget", title="Walking route maps",
    description="Shows the walking route steps and the floor plan of every level inline.",
    mime_type=ROUTE_WIDGET_MIME,
    meta={"ui": {"prefersBorder": True, "csp": {"resourceDomains": [PUBLIC_URL], "connectDomains": []}},
          "openai/widgetDescription": "Walking route steps with the floor plan of each level."},
)
def route_widget() -> str:
    return (ROOT / "app" / "route_widget.html").read_text(encoding="utf-8")


@mcp.tool(name="search_sessions", annotations=READ_ONLY)
def search_sessions_tool(
    query: str = "",
    date: str = "",
    from_time: str = "",
    to_time: str = "",
    content_area: str = "",
    area_of_interest: str = "",
    session_type: str = "",
    industry: str = "",
    speaker: str = "",
    company: str = "",
    room: str = "",
    level: str = "",
    limit: int = 25,
    exact: bool = False,
    sort: str = "date",
    hide_started: bool = False,
) -> dict[str, Any]:
    """Search sessions by free-text query and optional filters (date YYYY-MM-DD, from_time/to_time HH:MM).
    A full session title or code returns only that session (all its repeats). Put a phrase in double quotes, or set
    exact=true, to match that exact phrase in the session text. Set hide_started=true when the user wants what is still to come: it leaves out sessions that have finished
    and paid sessions that began more than 30 minutes ago (Las Vegas time). Results are the best matches, listed by date and start time (sort="relevance" lists the best match first).
    Sessions with arriveEarlyMinutes (labs, bootcamps, hackathons) are best entered that many minutes early.
    Sessions with paid=true (Oracle University Training, codes OUT...) need a separate paid registration through
    My Account: always tell the user this (see registrationNote) when you mention such a session."""
    filters = {
        "query": query, "date": date, "from": from_time, "to": to_time,
        "contentArea": content_area, "areaOfInterest": area_of_interest,
        "sessionType": session_type, "industry": industry, "speaker": speaker,
        "company": company, "room": room, "level": level, "limit": limit, "exact": exact, "sort": sort,
        "hideStarted": hide_started,
    }
    return with_disclaimer({"results": search_sessions(sessions(), filters)})


@mcp.tool(annotations=READ_ONLY)
def get_session_by_code(code: str) -> dict[str, Any]:
    """Get one session by its session code, e.g. LRN2141."""
    return with_disclaimer(get_by_code(sessions(), code) or {"error": "Session not found"})


@mcp.tool(annotations=READ_ONLY)
def find_session_conflicts(codes: list[str], minimum_transition_minutes: int = 0) -> dict[str, Any]:
    """Find overlapping or too-tightly-scheduled sessions among the given session codes."""
    return with_disclaimer(find_conflicts(sessions(), codes, minimum_transition_minutes))


@mcp.tool(annotations=READ_ONLY, meta=ROUTE_WIDGET_TOOL_META)
def check_transition(code_a: str, code_b: str, step_free: bool = False, early_arrival: bool = True) -> CallToolResult:
    """Can someone walk from one session to the other? Uses venue maps; the result is an estimate.
    Verdict: ok, tight, unlikely, overlap or unknown (room not yet published).
    lateIfWalking gives the minutes late on arrival for the best and worst walking estimate.
    Set step_free=true only when the user asks for elevators or step-free access (reduced mobility):
    the route then avoids escalators and includes the wait for the lift.
    Hands-on sessions (labs, bootcamps, hackathons) are best entered 30 min early (arriveBy); set
    early_arrival=false only if the user says they will walk in at the start."""
    a, b = get_by_code(sessions(), code_a), get_by_code(sessions(), code_b)
    if not a or not b:
        return with_map_images({"error": "Session not found"})
    return with_map_images(with_disclaimer(absolute_maps(assess_transition(a, b, step_free, early_arrival) | {"venueWarning": venue()["warning"]})))


@mcp.tool(annotations=READ_ONLY, meta=ROUTE_WIDGET_TOOL_META)
def get_walk_route(from_place: str, to_place: str, step_free: bool = False) -> CallToolResult:
    """Step-by-step walking route between two places at the Venetian Expo, with distance, levels and
    schematic floor plan image URLs (one per level, route drawn on it). Places are free text such as
    'Hall G', 'Titian', 'Galileo 1001, Level 1', 'Hub' or a room number. Estimates only; show the map
    URLs (PNG images) to the user as images or links. ALWAYS also give the user routeDetail.pageUrl as a
    clickable link ("Open the route maps"): many chat clients cannot embed images. Set step_free=true only when the user asks for
    elevators or step-free access: the route then uses elevators, never escalators."""
    za, zb = resolve_place(from_place), resolve_place(to_place)
    if not za or not zb:
        return with_map_images(with_disclaimer({"error": "Could not place: " + ", ".join(p for p, z in ((from_place, za), (to_place, zb)) if not z)}))
    detail = route_details(za, zb, step_free, place_room(from_place, za), place_room(to_place, zb))
    if not detail:
        return with_map_images(with_disclaimer({"error": "No walking route known between these places"}))
    return with_map_images(with_disclaimer(absolute_maps({"from": from_place, "to": to_place, "routeDetail": detail,
                                                          "venueWarning": venue()["warning"]})))


@mcp.tool(annotations=READ_ONLY)
def find_booth(query: str, limit: int = 5) -> dict[str, Any]:
    """Find a sponsor stand (booth), a Hub theater or a named Hub area at Oracle AI World by booth number ('4009'),
    company name ('NVIDIA', partial names work), theater ('Theater 3') or area ('ACE Lounge', 'Oracle TV',
    'SWAG Station', 'The Shop', 'zone F'). Areas have kind "area" and are not sponsor booths. Returns booth number, company, row, and a map link
    (routeDetail.pageUrl) that shows where it is on the Hub plan, with the walking route from the Hub entrance.
    Booths are in the Hub on Level 2 (Hall C). Positions on the plan are approximate. For walking between two
    stands use get_walk_route with 'Booth 2003' and 'NVIDIA' (names or numbers) as the places."""
    from .hub import find_areas, find_booths

    n = max(1, min(limit, 20))
    found = ([dict(b, kind="booth") for b in find_booths(query, n)] + find_areas(query, n))[:n]
    for f in found:
        place = f["name"] if f["kind"] != "booth" else f"Booth {f['number']}"
        detail = route_details("hub", "hub", False, None, f["number"])
        if detail:
            f["routeDetail"] = {"pageUrl": PUBLIC_URL + detail["pageUrl"], "pngUrl": PUBLIC_URL + detail["mapUrls"][0]["pngUrl"],
                                "meters": detail["meters"], "levels": [6]}
        f["place"] = place
    return with_disclaimer({"query": query, "results": found, "count": len(found), "location": "Oracle AI World Hub, Level 2 (Hall C)",
                            "venueWarning": venue()["warning"]})


@mcp.tool(annotations=READ_ONLY)
def get_route_map_images(from_place: str, to_place: str, step_free: bool = False) -> CallToolResult:
    """The floor plan images (one PNG per level, route drawn on it) for a walk between two places, as image
    content. get_walk_route already returns these images; use this only to get the maps alone."""
    za, zb = resolve_place(from_place), resolve_place(to_place)
    detail = route_details(za, zb, step_free, place_room(from_place, za), place_room(to_place, zb)) if za and zb else None
    if not detail:
        return CallToolResult(content=[TextContent(type="text", text="No walking route known between these places")], isError=True)
    res = with_map_images(with_disclaimer(absolute_maps({"from": from_place, "to": to_place, "routeDetail": detail})))
    return CallToolResult(content=[c for c in res.content if c.type == "image"] + [TextContent(type="text", text=DISCLAIMER)])


@mcp.tool(annotations=READ_ONLY)
def check_walk(from_place: str, to_place: str, gap_minutes: int, step_free: bool = False) -> dict[str, Any]:
    """Walking check between two places with a given gap, for custom stops such as lunch or networking.
    Places are free text: 'Hall G', 'Oracle AI World Hub', 'Galileo 1001, Level 1', 'Titian 2204'.
    Returns the best/worst walking minutes and lateIfWalking (minutes late on arrival). An estimate.
    Set step_free=true only when the user asks for elevators or step-free access."""
    return with_disclaimer(check_move(from_place, to_place, gap_minutes, step_free) | {"venueWarning": venue()["warning"]})


@mcp.tool(annotations=READ_ONLY)
def plan_strict_day(
    date: str,
    topics: list[str],
    late_tolerance_minutes: int = 2,
    lateness_basis: str = "worst",
    include_hub_talks: bool = True,
    include_keynote: bool = False,
    lunch_minutes: int = 30,
    lunch_from: str = "12:00",
    lunch_until: str = "14:00",
    networking_blocks: int = 2,
    networking_minutes: int = 20,
    networking_from: str = "11:00",
    networking_until: str = "18:00",
    day_start: str = "08:00",
    day_end: str = "18:00",
    fixed_commitments: list[dict[str, str]] | None = None,
    hide_started: bool = False,
    strict_early: bool = False,
) -> dict[str, Any]:
    """Plan one day with no overlaps and a limit on how late you may arrive (the best plan by topic score).
    Includes a lunch block in Hall G and networking blocks in the Hub. lateness_basis is 'worst' (safe) or
    'best' (hurrying) walking time. HH:MM times; estimates only.
    Hands-on sessions (labs, bootcamps, hackathons) are best entered about 30 min early: moves show whether the gap
    allows it and warnings list where it does not. strict_early=true plans with that early arrival as a hard rule.
    Returns schedule, moves (gap, walking range, lateIfWalking), dropped sessions with reasons, and warnings."""
    return with_disclaimer(plan_day(
        sessions(), date, topics, late_tolerance_minutes, lateness_basis, include_hub_talks, include_keynote,
        lunch_minutes, (lunch_from, lunch_until), networking_blocks, networking_minutes,
        (networking_from, networking_until), day_start, day_end, fixed_commitments, hide_started=hide_started,
        strict_early=strict_early,
    ) | {"venueWarning": venue()["warning"]})


@mcp.tool(name="optimize_agenda", annotations=READ_ONLY)
def optimize_agenda_tool(
    date: str,
    interests: list[str],
    minimum_transition_minutes: int = 10,
    fixed_commitments: list[dict[str, str]] | None = None,
    hide_started: bool = False,
) -> dict[str, Any]:
    """Propose a conflict-free agenda for a day. hide_started=true skips finished sessions and paid sessions that began over 30 minutes ago. fixed_commitments: [{"title","startTime","endTime"}] (HH:MM)."""
    body = {
        "date": date,
        "interests": interests,
        "preferences": {"minimumTransitionMinutes": minimum_transition_minutes},
        "fixedCommitments": fixed_commitments or [],
        "hideStarted": hide_started,
    }
    return with_disclaimer(optimize_agenda(sessions(), body))


@mcp.tool(annotations=READ_ONLY)
def get_catalog_metadata() -> dict[str, Any]:
    """Describe the catalog snapshot (source, extraction date, counts)."""
    return with_disclaimer(catalog()["catalog"])


# ChatGPT-compatible `search` / `fetch` tools (required for deep research / company knowledge).
@mcp.tool(annotations=READ_ONLY)
def search(query: str) -> str:
    """Search Oracle AI World sessions. Returns JSON: {"results":[{"id","title","url"}]}."""
    results = [
        {"id": s.get("code"), "title": f"{s.get('code')} - {s.get('title')}", "url": s.get("url") or ""}
        for s in search_sessions(sessions(), {"query": query, "limit": 20})
    ]
    return json.dumps({"results": results, "disclaimer": DISCLAIMER}, ensure_ascii=False)


@mcp.tool(annotations=READ_ONLY)
def fetch(id: str) -> str:
    """Fetch a session by id (its session code). Returns JSON: {"id","title","text","url","metadata"}."""
    s = get_by_code(sessions(), id)
    if not s:
        return json.dumps({"error": "Session not found"})
    text = "\n".join(f"{k}: {v}" for k, v in s.items() if v not in (None, "", []))
    return json.dumps(
        {"id": s.get("code"), "title": s.get("title"), "text": text + "\ndisclaimer: " + DISCLAIMER,
         "url": s.get("url") or "", "metadata": s, "disclaimer": DISCLAIMER},
        ensure_ascii=False,
    )


def main() -> None:
    from . import rest_routes  # noqa: F401  (registers REST routes)

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
