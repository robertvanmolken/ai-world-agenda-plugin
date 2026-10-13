"""Legacy REST routes (ChatGPT OpenAPI/plugin flow), registered on the MCP app."""
from __future__ import annotations

import json
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .catalog import find_conflicts, get_by_code, optimize_agenda, search_sessions
from .mcp_server import ROOT, catalog, mcp, sessions


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


@mcp.custom_route("/logo.png", methods=["GET"])
async def logo(request: Request) -> Response:
    path = ROOT / "logo.png"
    if not path.exists():
        return JSONResponse({"error": "Not found"}, status_code=404)
    return Response(path.read_bytes(), media_type="image/png")


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
