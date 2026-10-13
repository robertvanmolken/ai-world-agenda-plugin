"""Legacy REST routes (ChatGPT OpenAPI/plugin flow), registered on the MCP app."""
from __future__ import annotations

import json
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .catalog import find_conflicts, get_by_code, optimize_agenda, search_sessions
from .mcp_server import ROOT, catalog, mcp, sessions
from .venue import assess_transition, venue


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
    "/favicon.png": "favicon.png",
    "/favicon.ico": "favicon.png",
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
    return JSONResponse({"results": search_sessions(sessions(), dict(request.query_params))})


@mcp.custom_route("/sessions/code/{code}", methods=["GET"])
async def rest_session_code(request: Request) -> Response:
    s = get_by_code(sessions(), request.path_params["code"])
    return JSONResponse(s or {"error": "Session not found"}, status_code=200 if s else 404)


@mcp.custom_route("/sessions/search", methods=["POST"])
async def rest_search(request: Request) -> Response:
    body = await _json_body(request)
    if body is None:
        return _BAD
    return JSONResponse({"results": search_sessions(sessions(), body)})


@mcp.custom_route("/sessions/conflicts", methods=["POST"])
async def rest_conflicts(request: Request) -> Response:
    body = await _json_body(request)
    if body is None:
        return _BAD
    minutes = int(body.get("minimumTransitionMinutes") or 0)
    return JSONResponse(find_conflicts(sessions(), body.get("codes") or [], minutes))


@mcp.custom_route("/agenda/optimize", methods=["POST"])
async def rest_optimize(request: Request) -> Response:
    body = await _json_body(request)
    if body is None:
        return _BAD
    return JSONResponse(optimize_agenda(sessions(), body))



@mcp.custom_route("/sessions/transition", methods=["POST"])
async def rest_transition(request: Request) -> Response:
    body = await _json_body(request)
    if body is None:
        return _BAD
    a, b = get_by_code(sessions(), body.get("codeA") or ""), get_by_code(sessions(), body.get("codeB") or "")
    if not a or not b:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return JSONResponse(assess_transition(a, b) | {"venueWarning": venue()["warning"]})
