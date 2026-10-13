"""ASGI entrypoint: uvicorn app.asgi:app --host 0.0.0.0 --port $PORT

Serves MCP (Streamable HTTP) at /mcp plus the legacy REST routes.
"""
from starlette.middleware.cors import CORSMiddleware

from . import rest_routes  # noqa: F401  (registers REST routes)
from .mcp_server import mcp

app = mcp.streamable_http_app()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS", "HEAD", "DELETE"],
    allow_headers=["*"],
    expose_headers=["Mcp-Session-Id"],
)
