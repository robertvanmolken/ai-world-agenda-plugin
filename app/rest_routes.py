"""Legacy REST routes (ChatGPT OpenAPI/plugin flow), registered on the MCP app."""
from __future__ import annotations

import html
import json
import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .catalog import find_conflicts, get_by_code, optimize_agenda, search_sessions
from .mcp_server import ROOT, catalog, mcp, sessions, with_disclaimer
from .planner import plan_day
from .hub import find_areas, find_booths
from .mapsvg import levels as map_levels, render_level
from .mappng import render_level_png
from .routing import place_room, room_key, route_range
from .venue import assess_transition, resolve_place, route_details, venue


def _flag(value: Any) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _label_of(zone: str) -> str:
    return venue()["hub"]["name"] if zone == "hub" else venue()["zones"][zone]["name"]


def _room(q: Any, side: str, zone: str | None) -> str | None:
    """Room for one end of a route: an explicit fromRoom/toRoom key, else a room named in the place text."""
    return room_key(zone, q.get(side + "Room")) or place_room(q.get(side, ""), zone) if zone else None


def _origin(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return f"{proto}://{request.headers.get('host', 'localhost:8787')}"


async def _json_body(request: Request) -> dict[str, Any] | None:
    try:
        body = await request.json()
    except Exception:
        return None
    return body if isinstance(body, dict) else None


_BAD = JSONResponse({"error": "Invalid JSON"}, status_code=400)


@mcp.custom_route("/", methods=["GET", "HEAD"])
async def root(request: Request) -> Response:
    return Response((ROOT / "static" / "index.html").read_bytes(), media_type="text/html; charset=utf-8")


@mcp.custom_route("/status", methods=["GET"])
async def status(request: Request) -> Response:
    return JSONResponse({
        "name": "Oracle AI World 2026 Agenda Assistant", "status": "ok", "sessions": len(sessions()),
        "mcp": "/mcp", "openapi": "/openapi.yaml", "health": "/health", "catalogMetadata": "/catalog/meta",
    })


@mcp.custom_route("/health", methods=["GET", "HEAD"])
async def health(request: Request) -> Response:
    return JSONResponse({"ok": True, "sessions": len(sessions())})


@mcp.custom_route("/catalog/meta", methods=["GET"])
async def catalog_meta(request: Request) -> Response:
    return JSONResponse(catalog()["catalog"])


@mcp.custom_route("/openapi.yaml", methods=["GET"])
async def openapi(request: Request) -> Response:
    return Response((ROOT / "openapi.yaml").read_bytes(), media_type="application/yaml")


@mcp.custom_route("/.well-known/ai-plugin.json", methods=["GET"])
async def manifest(request: Request) -> Response:
    data = json.loads((ROOT / ".well-known" / "ai-plugin.json").read_text("utf-8"))
    origin = _origin(request)
    data["api"]["url"] = f"{origin}/openapi.yaml"
    data["logo_url"] = f"{origin}/logo.png"
    return JSONResponse(data)


# Only these resized files are served; the full-size emblem in the repo root is never exposed.
_ICONS = {
    "/logo.png": "icon-512.png",
    "/icon.png": "icon-512.png",
    "/icon-192.png": "icon-192.png",
    "/icon-64.png": "icon-64.png",
    "/og-image.png": "og-image.png",
    "/favicon.png": "favicon.png",
    "/favicon.ico": "favicon.png",
    "/exoblock_logo.png": "exoblock_logo.png",
}


def _icon_route(path: str, filename: str) -> None:
    @mcp.custom_route(path, methods=["GET", "HEAD"])
    async def _serve(request: Request) -> Response:
        f = ROOT / "static" / filename
        if not f.exists():
            return JSONResponse({"error": "Not found"}, status_code=404)
        return Response(f.read_bytes(), media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})


for _path, _file in _ICONS.items():
    _icon_route(_path, _file)


# Self-hosted fonts (SIL Open Font License). Fixed whitelist of file names.
_FONTS = ["plus-jakarta-sans.woff2", "source-serif-4.woff2", "source-serif-4-italic.woff2"]


def _font_route(filename: str) -> None:
    @mcp.custom_route(f"/fonts/{filename}", methods=["GET", "HEAD"])
    async def _serve(request: Request) -> Response:
        return Response((ROOT / "static" / "fonts" / filename).read_bytes(), media_type="font/woff2",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


for _name in _FONTS:
    _font_route(_name)


@mcp.custom_route("/sessions", methods=["GET"])
async def rest_sessions(request: Request) -> Response:
    return JSONResponse(with_disclaimer({"results": search_sessions(sessions(), dict(request.query_params))}))


@mcp.custom_route("/sessions/code/{code}", methods=["GET"])
async def rest_session_code(request: Request) -> Response:
    s = get_by_code(sessions(), request.path_params["code"])
    return JSONResponse(with_disclaimer(s or {"error": "Session not found"}), status_code=200 if s else 404)


@mcp.custom_route("/sessions/search", methods=["POST"])
async def rest_search(request: Request) -> Response:
    body = await _json_body(request)
    if body is None:
        return _BAD
    return JSONResponse(with_disclaimer({"results": search_sessions(sessions(), body)}))


@mcp.custom_route("/booths/search", methods=["GET", "POST"])
async def rest_booths(request: Request) -> Response:
    """Find a sponsor booth by number or company name, or a Hub theater ('Theater 3')."""
    if request.method == "POST":
        body = await _json_body(request)
        if body is None:
            return _BAD
        query, limit = str(body.get("query") or ""), body.get("limit")
    else:
        query, limit = request.query_params.get("q", ""), request.query_params.get("limit")
    try:
        n = max(1, min(int(limit or 10), 50))
    except ValueError:
        return _BAD
    found = [dict(b, kind="booth") for b in find_booths(query, n)] + find_areas(query, n)
    found = found[:n]
    if found and found[0]["kind"] == "area" and not any(f["kind"] == "booth" for f in found):
        pass  # areas only: nothing else to add
    for f in found:
        f["routeDetail"] = route_details("hub", "hub", False, None, f["number"])
    return JSONResponse(with_disclaimer({"query": query, "results": found, "count": len(found),
                                         "location": "Oracle AI World Hub, Level 2 (Hall C)"}))


@mcp.custom_route("/sessions/conflicts", methods=["POST"])
async def rest_conflicts(request: Request) -> Response:
    body = await _json_body(request)
    if body is None:
        return _BAD
    minutes = int(body.get("minimumTransitionMinutes") or 0)
    return JSONResponse(with_disclaimer(find_conflicts(sessions(), body.get("codes") or [], minutes)))


@mcp.custom_route("/agenda/optimize", methods=["POST"])
async def rest_optimize(request: Request) -> Response:
    body = await _json_body(request)
    if body is None:
        return _BAD
    return JSONResponse(with_disclaimer(optimize_agenda(sessions(), body)))



@mcp.custom_route("/sessions/transition", methods=["POST"])
async def rest_transition(request: Request) -> Response:
    body = await _json_body(request)
    if body is None:
        return _BAD
    a, b = get_by_code(sessions(), body.get("codeA") or ""), get_by_code(sessions(), body.get("codeB") or "")
    if not a or not b:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return JSONResponse(with_disclaimer(assess_transition(a, b, _flag(body.get("stepFree")), body.get("earlyArrival", True) not in (False, "false", "0", 0)) | {"venueWarning": venue()["warning"]}))


@mcp.custom_route("/sessions/route", methods=["POST"])
async def rest_route(request: Request) -> Response:
    body = await _json_body(request)
    if body is None:
        return _BAD
    za, zb = resolve_place(str(body.get("from") or "")), resolve_place(str(body.get("to") or ""))
    if not za or not zb:
        return JSONResponse({"error": "Could not place from/to"}, status_code=404)
    detail = route_details(za, zb, _flag(body.get("stepFree")), place_room(str(body.get("from") or ""), za), place_room(str(body.get("to") or ""), zb))
    if not detail:
        return JSONResponse({"error": "No walking route known"}, status_code=404)
    return JSONResponse(with_disclaimer({"from": za, "to": zb, "routeDetail": detail, "venueWarning": venue()["warning"]}))


_SVG = {"Cache-Control": "public, max-age=3600"}


@mcp.custom_route("/venue/map/{level}.svg", methods=["GET"])
async def venue_map(request: Request) -> Response:
    try:
        level = int(request.path_params["level"])
    except ValueError:
        return JSONResponse({"error": "Not found"}, status_code=404)
    if level not in map_levels():
        return JSONResponse({"error": "Not found"}, status_code=404)
    return Response(render_level(level), media_type="image/svg+xml", headers=_SVG)


@mcp.custom_route("/venue/route", methods=["GET"])
async def venue_route(request: Request) -> Response:
    """SVG floor plan with the walking route drawn on it. Query: from, to (zone ids or places), level."""
    q = request.query_params
    za, zb = resolve_place(q.get("from", "")), resolve_place(q.get("to", ""))
    ra, rb = _room(q, "from", za), _room(q, "to", zb)
    r = route_range(za, zb, _flag(q.get("stepFree")), ra, rb) if za and zb else None
    if not r:
        return JSONResponse({"error": "No route"}, status_code=404)
    try:
        level = int(q.get("level") or r["levels"][0])
    except ValueError:
        return JSONResponse({"error": "Invalid level"}, status_code=400)
    if level not in map_levels():
        return JSONResponse({"error": "Not found"}, status_code=404)
    return Response(render_level(level, r), media_type="image/svg+xml", headers=_SVG)


_PNG = {"Cache-Control": "public, max-age=3600"}


@mcp.custom_route("/venue/route/page", methods=["GET"])
async def venue_route_page(request: Request) -> Response:
    """Small HTML page with the steps and the map of every level, to open from a chat link."""
    q = request.query_params
    za, zb = resolve_place(q.get("from", "")), resolve_place(q.get("to", ""))
    ra, rb = _room(q, "from", za), _room(q, "to", zb)
    sf = _flag(q.get("stepFree"))
    r = route_range(za, zb, sf, ra, rb) if za and zb else None
    if not r:
        return JSONResponse({"error": "No route"}, status_code=404)
    d = route_details(za, zb, sf, ra, rb) or {}
    steps = "".join(f"<li>{html.escape(s['text'])}</li>" for s in r["steps"])
    maps = "".join(
        f'<h2>{html.escape(m.get("label") or "Level " + str(m["level"]))}</h2><a href="{html.escape(m["pngUrl"])}"><img src="{html.escape(m["pngUrl"])}" alt="Route on Level {m["level"]}"></a>'
        for m in d.get("mapUrls", [])
    )
    title = f"{html.escape(q.get('from', ''))} to {html.escape(q.get('to', ''))}"
    body = (
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>Walking route {title}</title>"
        "<style>body{font:16px/1.5 system-ui,sans-serif;max-width:900px;margin:24px auto;padding:0 16px;color:#2B1A20}"
        "img{width:100%;border:1px solid #E5D9D0;border-radius:12px}h1{font-size:1.4rem}h2{font-size:1.1rem;margin-top:24px}"
        "small{color:#76686B}</style>"
        f"<h1>Walking route: {html.escape(_label_of(za))} to {html.escape(_label_of(zb))}</h1>"
        f"<p>About {r['meters']} m{' (step-free, elevators only)' if sf else ''}.</p><ol>{steps}</ol>{maps}"
        "<p><small>Schematic floor plans, not to scale. Estimates only; verify in the official event app.</small></p>"
    )
    return Response(body, media_type="text/html; charset=utf-8", headers=_PNG)


@mcp.custom_route("/venue/map/{level}.png", methods=["GET"])
async def venue_map_png(request: Request) -> Response:
    try:
        level = int(request.path_params["level"])
    except ValueError:
        return JSONResponse({"error": "Not found"}, status_code=404)
    if level not in map_levels():
        return JSONResponse({"error": "Not found"}, status_code=404)
    return Response(render_level_png(level), media_type="image/png", headers=_PNG)


@mcp.custom_route("/venue/route.png", methods=["GET"])
async def venue_route_png(request: Request) -> Response:
    """PNG twin of /venue/route, for clients that cannot show SVG (ChatGPT)."""
    q = request.query_params
    za, zb = resolve_place(q.get("from", "")), resolve_place(q.get("to", ""))
    ra, rb = _room(q, "from", za), _room(q, "to", zb)
    r = route_range(za, zb, _flag(q.get("stepFree")), ra, rb) if za and zb else None
    if not r:
        return JSONResponse({"error": "No route"}, status_code=404)
    try:
        level = int(q.get("level") or r["levels"][0])
    except ValueError:
        return JSONResponse({"error": "Invalid level"}, status_code=400)
    if level not in map_levels():
        return JSONResponse({"error": "Not found"}, status_code=404)
    return Response(render_level_png(level, r), media_type="image/png", headers=_PNG)


@mcp.custom_route("/agenda/plan", methods=["POST"])
async def rest_plan(request: Request) -> Response:
    body = await _json_body(request)
    if body is None or not body.get("date"):
        return _BAD
    r = body.get("rules") or {}
    result = plan_day(
        sessions(), body["date"], body.get("topics") or [],
        int(r.get("lateToleranceMinutes", 2)), r.get("latenessBasis", "worst"),
        bool(r.get("includeHubTalks", True)), bool(r.get("includeKeynote", False)),
        int(r.get("lunchMinutes", 30)), tuple(r.get("lunchWindow", ["12:00", "14:00"])),
        int(r.get("networkingBlocks", 2)), int(r.get("networkingMinutes", 20)),
        tuple(r.get("networkingWindow", ["11:00", "18:00"])),
        r.get("dayStart", "08:00"), r.get("dayEnd", "18:00"), body.get("fixedCommitments"),
        hide_started=bool(body.get("hideStarted") or r.get("hideStarted")),
        strict_early=bool(r.get("strictEarly", False)),
    )
    return JSONResponse(with_disclaimer(result | {"venueWarning": venue()["warning"]}))
