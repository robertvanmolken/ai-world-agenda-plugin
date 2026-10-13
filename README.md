# Oracle AI World 2026 Agenda Assistant

> Unofficial community tool. Not affiliated with or endorsed by Oracle. The bundled catalog is a snapshot and critical details should be verified in the official Oracle catalog. — snapshot plugin prototype

This project turns a **saved Oracle AI World session catalog HTML page** into a sanitized JSON catalog and a small REST API that an AI client can use to search sessions, detect conflicts, and propose a personal agenda.

It is intentionally snapshot-based: **no Oracle SSO credentials, cookies, MFA automation, or login bypass are used**.

## What is included

- `data/sessions.json` — sanitized catalog extracted from the HTML snapshot used in this chat.
- `app/catalog_parser.py` — zero-dependency parser for a newly saved catalog HTML file.
- `app/server.py` — zero-dependency local REST API.
- `openapi.yaml` — tool/API schema for an AI client.
- `.well-known/ai-plugin.json` — legacy-compatible manifest template. Modern ChatGPT plugin/custom integration setup may use the OpenAPI file or another connector mechanism depending on the account/product surface.
- agenda optimization and conflict detection helpers.
- unit tests.

The original saved Oracle HTML is **not bundled** because authenticated pages can contain account/session metadata. Only parsed session information is shipped.

## Quick start

Requires Python 3.10+.

```bash
cd ai-world-agenda-plugin
python -m unittest discover -s tests -v
python -m app.server
```

API runs on:

```text
http://127.0.0.1:8787
```

Examples:

```bash
curl 'http://127.0.0.1:8787/health'

curl 'http://127.0.0.1:8787/sessions?date=2026-10-27&keyword=integration'

curl 'http://127.0.0.1:8787/sessions/code/LRN2141'
```

Search:

```bash
curl -X POST http://127.0.0.1:8787/sessions/search \
  -H 'Content-Type: application/json' \
  -d '{"date":"2026-10-27","query":"AI agents integration MCP","limit":10}'
```

Conflict detection:

```bash
curl -X POST http://127.0.0.1:8787/sessions/conflicts \
  -H 'Content-Type: application/json' \
  -d '{"codes":["LRN2141","MET2725"],"minimumTransitionMinutes":10}'
```

Agenda proposal:

```bash
curl -X POST http://127.0.0.1:8787/agenda/optimize \
  -H 'Content-Type: application/json' \
  -d '{
    "date":"2026-10-27",
    "interests":["Oracle Integration","AI Agents","MCP","partner growth","customer case studies"],
    "preferences":{"minimumTransitionMinutes":10},
    "fixedCommitments":[
      {"title":"ACE volunteering","startTime":"14:00","endTime":"15:00"},
      {"title":"Oracle Vision and Strategy","startTime":"15:30","endTime":"17:00"}
    ]
  }'
```

## Refresh from a newer HTML snapshot

1. Log into Oracle AI World normally in your browser.
2. Open the session catalog and save the **complete rendered HTML page** locally.
3. Do **not** publish that authenticated HTML file.
4. Run:

```bash
python -m app.catalog_parser '/path/to/Session Catalog - Session Catalog.html' --out data/sessions.json
```

5. Restart the API.

The parser extracts only catalog tiles and ignores Oracle SSO/account metadata outside those tiles.

## API operations

- `GET /health`
- `GET /catalog/meta`
- `GET /sessions`
- `GET /sessions/code/{code}`
- `POST /sessions/search`
- `POST /sessions/conflicts`
- `POST /agenda/optimize`

## Connecting it to Claude and ChatGPT (MCP, recommended)

The server speaks the Model Context Protocol, which both Claude and ChatGPT support. Tools: `search_sessions`, `get_session_by_code`, `find_session_conflicts`, `optimize_agenda`, `get_catalog_metadata`, plus ChatGPT-style `search` and `fetch`.

Install and run (Python 3.10+):

```bash
pip install -r requirements.txt
uvicorn app.asgi:app --port 8787      # remote MCP at http://127.0.0.1:8787/mcp, plus REST routes
```

**Claude.ai** — Settings → Connectors → Add custom connector → `https://YOUR-SERVICE.onrender.com/mcp`.

**Claude Code** — `claude mcp add --transport http ai-world https://YOUR-SERVICE.onrender.com/mcp`

**Claude Desktop (local stdio)** — add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ai-world-agenda": {
      "command": "python",
      "args": ["-m", "app.mcp_server"],
      "cwd": "/absolute/path/to/ai-world-agenda-plugin"
    }
  }
}
```

**ChatGPT** — Settings → Connectors → Advanced → enable Developer mode, then create a connector with URL `https://YOUR-SERVICE.onrender.com/mcp` (no authentication).

Optional env vars: `ALLOWED_HOSTS` (comma-separated hostnames to enable host validation, e.g. `YOUR-SERVICE.onrender.com`), `AI_WORLD_DATA` (alternate catalog JSON).

Render: `render.yaml` now starts `uvicorn app.asgi:app --host 0.0.0.0 --port $PORT`. If you configured the service manually, change the start command to that. The Starter plan (always on, no cold starts) is recommended for connectors; free-tier spin-down can make the first connector call time out.

## Connecting it to ChatGPT (legacy OpenAPI plugin/actions)

The useful artifact is `openapi.yaml`. Host this API on an HTTPS endpoint accessible to ChatGPT, then use the custom-plugin/connector/action mechanism available in your ChatGPT workspace to register the API schema.

`localhost` is only for development; a hosted integration needs an HTTPS URL. Update the `servers:` entry in `openapi.yaml` after deployment.


## Deploy on Render

This package is Render-ready. The server binds to `0.0.0.0` and reads Render's `PORT` environment variable automatically.

### Option A — Blueprint (`render.yaml`)

1. Create a GitHub repository and push this project to it.
2. In Render, choose **New > Blueprint**.
3. Connect the GitHub repository.
4. Render detects `render.yaml` and creates the web service (Starter plan).
5. Wait for the deploy to finish.
6. Open the generated URL, for example:

```text
https://ai-world-agenda.onrender.com
```

Verify:

```text
https://YOUR-SERVICE.onrender.com/health
https://YOUR-SERVICE.onrender.com/openapi.yaml
https://YOUR-SERVICE.onrender.com/.well-known/ai-plugin.json
```

### Option B — Manual Render Web Service

Use these settings:

```text
Runtime: Python
Build command: pip install -r requirements.txt
Start command: uvicorn app.asgi:app --host 0.0.0.0 --port $PORT
Health check path: /health
Plan: Starter
```

No database, secret, or persistent disk is required for the bundled snapshot.

### OpenAPI on Render

`openapi.yaml` uses a same-origin server URL (`/`), so you do **not** need to edit it for your Render hostname. The legacy plugin manifest is generated dynamically from the incoming host and HTTPS proxy headers, so it also points to the deployed Render URL automatically.

### Plan note

The Starter plan stays always on, so there are no cold starts. A free Render service spins down when idle, which can make the first MCP connector call time out.

## Snapshot limitation

This catalog is not live. A session's time, room, capacity, speaker list, or title can change. The API therefore exposes `GET /catalog/meta` and the assistant should always treat the official Oracle catalog as authoritative for final event logistics.

## Privacy/security

This prototype deliberately:

- does not include the original authenticated HTML snapshot;
- does not store Oracle passwords;
- does not store Oracle cookies or SSO tokens;
- does not automate MFA;
- does not attempt to bypass Oracle access controls.

## Next useful iteration

Add an authenticated **admin-only upload endpoint** that accepts a newly saved HTML snapshot, sanitizes it, rebuilds `sessions.json`, and discards the raw HTML. This would make refreshing the plugin very easy without solving Oracle SSO.
