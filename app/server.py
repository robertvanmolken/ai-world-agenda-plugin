from __future__ import annotations

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .catalog import find_conflicts, get_by_code, load_catalog, optimize_agenda, search_sessions

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = Path(os.environ.get("AI_WORLD_DATA", ROOT / "data" / "sessions.json"))


def _bytes(handler: BaseHTTPRequestHandler, status: int, body: bytes, content_type: str) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def _json(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    server_version = "AIWorldAgenda/0.1"

    @property
    def catalog(self):
        if not hasattr(self.server, "catalog"):
            self.server.catalog = load_catalog(DATA_FILE)  # type: ignore[attr-defined]
        return self.server.catalog  # type: ignore[attr-defined]

    @property
    def sessions(self):
        return self.catalog["sessions"]

    def log_message(self, fmt, *args):
        if os.environ.get("QUIET") != "1":
            super().log_message(fmt, *args)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[-1] for k, v in parse_qs(u.query).items()}
        if u.path == "/openapi.yaml":
            return _bytes(self, 200, (ROOT / "openapi.yaml").read_bytes(), "application/yaml; charset=utf-8")
        if u.path == "/.well-known/ai-plugin.json":
            manifest = json.loads((ROOT / ".well-known" / "ai-plugin.json").read_text("utf-8"))
            proto = self.headers.get("X-Forwarded-Proto", "http")
            host = self.headers.get("Host", "localhost:8787")
            origin = f"{proto}://{host}"
            manifest["api"]["url"] = f"{origin}/openapi.yaml"
            manifest["logo_url"] = f"{origin}/logo.png"
            return _json(self, 200, manifest)
        if u.path == "/logo.png":
            logo = ROOT / "logo.png"
            if logo.exists():
                return _bytes(self, 200, logo.read_bytes(), "image/png")
        if u.path == "/":
            return _json(self, 200, {
                "name": "Oracle AI World 2026 Agenda Assistant",
                "status": "ok",
                "sessions": len(self.sessions),
                "openapi": "/openapi.yaml",
                "health": "/health",
                "catalogMetadata": "/catalog/meta",
            })
        if u.path == "/health":
            return _json(self, 200, {"ok": True, "sessions": len(self.sessions)})
        if u.path == "/catalog/meta":
            return _json(self, 200, self.catalog["catalog"])
        if u.path == "/sessions":
            return _json(self, 200, {"results": search_sessions(self.sessions, q)})
        m = re.fullmatch(r"/sessions/code/([A-Za-z0-9_-]+)", u.path)
        if m:
            s = get_by_code(self.sessions, m.group(1))
            return _json(self, 200 if s else 404, s or {"error": "Session not found"})
        return _json(self, 404, {"error": "Not found"})

    def _body(self):
        n = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return None

    def do_POST(self):
        body = self._body()
        if body is None:
            return _json(self, 400, {"error": "Invalid JSON"})
        if self.path == "/sessions/search":
            return _json(self, 200, {"results": search_sessions(self.sessions, body)})
        if self.path == "/sessions/conflicts":
            return _json(self, 200, find_conflicts(self.sessions, body.get("codes") or [], int(body.get("minimumTransitionMinutes") or 0)))
        if self.path == "/agenda/optimize":
            return _json(self, 200, optimize_agenda(self.sessions, body))
        return _json(self, 404, {"error": "Not found"})


def run():
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8787"))
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"AI World Agenda API: http://{host}:{port}")
    print(f"Dataset: {DATA_FILE}")
    httpd.serve_forever()


if __name__ == "__main__":
    run()
