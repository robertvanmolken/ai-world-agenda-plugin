"""ASGI entrypoint: uvicorn app.asgi:app --host 0.0.0.0 --port $PORT

Serves MCP (Streamable HTTP) at /mcp plus the legacy REST routes.
"""
from starlette.middleware.cors import CORSMiddleware

from . import clock
from . import rest_routes  # noqa: F401  (registers REST routes)
from .mcp_server import mcp


class SimulatedNow:
    """Let a REST request play another moment of the event: ?simulateNow=2026-10-27T10:30 or the X-Simulate-Now header.

    Only this request is affected, and only once the conference has ended is the default a simulated time."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        token = None
        if scope["type"] == "http":
            from urllib.parse import parse_qs

            query = parse_qs(scope.get("query_string", b"").decode("utf-8", "ignore"))
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
            moment = (query.get("simulateNow") or [headers.get("x-simulate-now", "")])[0]
            token = clock.set_simulated(moment)
        try:
            await self.app(scope, receive, send)
        finally:
            clock.reset_simulated(token)

app = mcp.streamable_http_app()
app.add_middleware(SimulatedNow)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS", "HEAD", "DELETE"],
    allow_headers=["*"],
    expose_headers=["Mcp-Session-Id"],
)
