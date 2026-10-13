"""MCP server (Claude, ChatGPT and any other MCP client) plus the legacy REST routes.

Run modes:
  python -m app.mcp_server            -> stdio (Claude Desktop / Claude Code local)
  uvicorn app.asgi:app                -> Streamable HTTP at /mcp (+ REST routes)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import Icon, ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .catalog import find_conflicts, get_by_code, load_catalog, optimize_agenda, search_sessions
from .venue import (
    apply_overrides,
    assess_transition,
    load_not_in_app,
    load_overrides,
    load_rooms,
    mark_not_in_app,
    merge_rooms,
    venue,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = Path(os.environ.get("AI_WORLD_DATA", ROOT / "data" / "sessions.json"))

PUBLIC_URL = os.environ.get("PUBLIC_URL", "https://ai-world-agenda-plugin.onrender.com").rstrip("/")

_catalog: dict[str, Any] | None = None


def catalog() -> dict[str, Any]:
    global _catalog
    if _catalog is None:
        _catalog = load_catalog(DATA_FILE)
        apply_overrides(_catalog["sessions"], load_overrides())
        merge_rooms(_catalog["sessions"], load_rooms())
        mark_not_in_app(_catalog["sessions"], load_not_in_app())
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


mcp = FastMCP(
    "Oracle AI World 2026 Agenda Assistant",
    instructions=(
        "Search the Oracle AI World 2026 session catalog (an unofficial snapshot), detect schedule "
        "conflicts and propose a personal agenda. Dates are ISO (YYYY-MM-DD), times are 24h HH:MM. "
        "Verify critical details in the official Oracle catalog."
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
) -> dict[str, Any]:
    """Search sessions by free-text query and optional filters (date YYYY-MM-DD, from_time/to_time HH:MM)."""
    filters = {
        "query": query, "date": date, "from": from_time, "to": to_time,
        "contentArea": content_area, "areaOfInterest": area_of_interest,
        "sessionType": session_type, "industry": industry, "speaker": speaker,
        "company": company, "room": room, "level": level, "limit": limit,
    }
    return {"results": search_sessions(sessions(), filters)}


@mcp.tool(annotations=READ_ONLY)
def get_session_by_code(code: str) -> dict[str, Any]:
    """Get one session by its session code, e.g. LRN2141."""
    return get_by_code(sessions(), code) or {"error": "Session not found"}


@mcp.tool(annotations=READ_ONLY)
def find_session_conflicts(codes: list[str], minimum_transition_minutes: int = 0) -> dict[str, Any]:
    """Find overlapping or too-tightly-scheduled sessions among the given session codes."""
    return find_conflicts(sessions(), codes, minimum_transition_minutes)


@mcp.tool(annotations=READ_ONLY)
def check_transition(code_a: str, code_b: str) -> dict[str, Any]:
    """Can someone walk from one session to the other? Uses venue maps; the result is an estimate.
    Verdict: ok, tight, unlikely, overlap or unknown (room not yet published)."""
    a, b = get_by_code(sessions(), code_a), get_by_code(sessions(), code_b)
    if not a or not b:
        return {"error": "Session not found"}
    return assess_transition(a, b) | {"venueWarning": venue()["warning"]}


@mcp.tool(name="optimize_agenda", annotations=READ_ONLY)
def optimize_agenda_tool(
    date: str,
    interests: list[str],
    minimum_transition_minutes: int = 10,
    fixed_commitments: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Propose a conflict-free agenda for a day. fixed_commitments: [{"title","startTime","endTime"}] (HH:MM)."""
    body = {
        "date": date,
        "interests": interests,
        "preferences": {"minimumTransitionMinutes": minimum_transition_minutes},
        "fixedCommitments": fixed_commitments or [],
    }
    return optimize_agenda(sessions(), body)


@mcp.tool(annotations=READ_ONLY)
def get_catalog_metadata() -> dict[str, Any]:
    """Describe the catalog snapshot (source, extraction date, counts)."""
    return catalog()["catalog"]


# ChatGPT-compatible `search` / `fetch` tools (required for deep research / company knowledge).
@mcp.tool(annotations=READ_ONLY)
def search(query: str) -> str:
    """Search Oracle AI World sessions. Returns JSON: {"results":[{"id","title","url"}]}."""
    results = [
        {"id": s.get("code"), "title": f"{s.get('code')} - {s.get('title')}", "url": s.get("url") or ""}
        for s in search_sessions(sessions(), {"query": query, "limit": 20})
    ]
    return json.dumps({"results": results}, ensure_ascii=False)


@mcp.tool(annotations=READ_ONLY)
def fetch(id: str) -> str:
    """Fetch a session by id (its session code). Returns JSON: {"id","title","text","url","metadata"}."""
    s = get_by_code(sessions(), id)
    if not s:
        return json.dumps({"error": "Session not found"})
    text = "\n".join(f"{k}: {v}" for k, v in s.items() if v not in (None, "", []))
    return json.dumps(
        {"id": s.get("code"), "title": s.get("title"), "text": text, "url": s.get("url") or "", "metadata": s},
        ensure_ascii=False,
    )


def main() -> None:
    from . import rest_routes  # noqa: F401  (registers REST routes)

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
