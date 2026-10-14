# Oracle AI World 2026 Agenda Assistant

> Unofficial community tool. Not affiliated with or endorsed by Oracle. The bundled catalog is a snapshot and critical details should be verified in the official Oracle catalog.

This project turns a **saved Oracle AI World session catalog HTML page** into a sanitized JSON catalog and serves it through:

- an **MCP server** (Model Context Protocol) that works with **Claude** and **ChatGPT**,
- a small **REST API** with an OpenAPI schema (legacy ChatGPT plugin/actions flow),
- a **landing page** with a session search box and connect instructions.

An AI client can use it to search sessions, detect conflicts, and propose a personal agenda.

It is intentionally snapshot-based: **no Oracle SSO credentials, cookies, MFA automation, or login bypass are used**.

## What is included

- `data/sessions.json` — sanitized catalog extracted from a saved HTML snapshot.
- `app/catalog_parser.py` — zero-dependency parser for a newly saved catalog HTML file.
- `app/catalog.py` — search, conflict detection and agenda optimization logic.
- `app/mcp_server.py` — MCP server (tools; stdio or Streamable HTTP at `/mcp`).
- `app/rest_routes.py` — REST routes and the landing page, registered on the MCP app.
- `app/asgi.py` — ASGI entrypoint combining MCP + REST (`uvicorn app.asgi:app`).
- `app/server.py` — legacy zero-dependency REST-only server (no MCP, no landing page).
- `static/index.html` — landing page with search box.
- `openapi.yaml` and `.well-known/ai-plugin.json` — legacy ChatGPT plugin/actions files.
- `render.yaml`, `Procfile` — Render deployment.
- `tests/` — unit tests.

The original saved Oracle HTML is **not bundled** (and is git-ignored under `data/`) because authenticated pages can contain account/session metadata. Only parsed session information is shipped.

## Quick start

Requires Python 3.10+.

```bash
cd ai-world-agenda-plugin
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
uvicorn app.asgi:app --port 8787
```

Then open:

| URL | What |
| --- | --- |
| `http://127.0.0.1:8787/` | Landing page with search |
| `http://127.0.0.1:8787/mcp` | MCP endpoint (Streamable HTTP) |
| `http://127.0.0.1:8787/status` | JSON status |
| `http://127.0.0.1:8787/health` | Health check |

Some tests (`test_mcp`, `test_web`) are skipped if `mcp`/`httpx` are not installed. `httpx` is only needed by the web tests: `pip install httpx`.

### REST examples

```bash
curl 'http://127.0.0.1:8787/health'
curl 'http://127.0.0.1:8787/sessions?date=2026-10-27&keyword=integration'
curl 'http://127.0.0.1:8787/sessions/code/LRN2141'

curl -X POST http://127.0.0.1:8787/sessions/search \
  -H 'Content-Type: application/json' \
  -d '{"date":"2026-10-27","query":"AI agents integration MCP","limit":10}'

curl -X POST http://127.0.0.1:8787/sessions/conflicts \
  -H 'Content-Type: application/json' \
  -d '{"codes":["LRN2141","MET2725"],"minimumTransitionMinutes":10}'

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

### Legacy dependency-free server

`python -m app.server` still runs a REST-only server on port 8787 with no third-party packages. It has no `/mcp` and no landing page.

## API operations

REST:

- `GET /` (landing page), `GET /status`, `GET /health`, `GET /catalog/meta`
- `GET /sessions`, `GET /sessions/code/{code}`
- `POST /sessions/search`, `POST /sessions/conflicts`, `POST /agenda/optimize`
- `GET /openapi.yaml`, `GET /.well-known/ai-plugin.json`, `GET /logo.png`

MCP (`/mcp`) tools, all read-only: `search_sessions`, `get_session_by_code`, `find_session_conflicts`, `optimize_agenda`, `get_catalog_metadata`, plus ChatGPT-style `search` and `fetch` (the session code is the id).

## Refresh from a newer HTML snapshot

1. Log into Oracle AI World normally in your browser.
2. Open the session catalog and save the **complete rendered HTML page** locally (for example into `data/`, which is git-ignored for `*.html` and `*_files/`).
3. Do **not** publish that authenticated HTML file.
4. Run:

```bash
python -m app.catalog_parser 'data/Session Catalog AI World.html' --out data/sessions.json
python -m unittest discover -s tests
```

5. Commit and push `data/sessions.json`. Render redeploys automatically (or restart the local server).

The parser extracts only catalog tiles and ignores Oracle SSO/account metadata outside those tiles.

## Rooms and "can I make it?" checks

Rooms come from the Oracle AI World mobile app, not from the catalog HTML (the catalog has no room data).
They are stored separately in `data/rooms.csv` (`code,room,area,level,location,source,capturedAt`) and merged
into the sessions by code on load, so refreshing the catalog never overwrites them.
Rooms are from the mobile app as of 2026-10-13 and cover only the sessions listed in that file; others show no room yet.

- `data/venue.json` models the Venetian Expo (levels 1-5) from the [official floor plans](https://www.venetianlasvegas.com/meetings/planning/spaces/expo-halls/expo-map-floor-plan.html). The map images themselves are not stored in the repo.
- The maps have no scale, so walking minutes are **rough estimates**, tuned in `venue.json` (`model` and each zone's `x`).
- The Oracle AI World Hub location is unconfirmed (`hub.confirmed: false`), so Hub transitions return a best/worst range over Halls A-D and G. Set `confirmed` and the `candidates` list once it is known.
- MCP tool `check_transition(code_a, code_b)` and REST `POST /sessions/transition` return `ok`, `tight`, `unlikely`, `overlap` or `unknown`. `find_session_conflicts` also returns `travel`, and `optimize_agenda` skips sessions that are unlikely to be reachable.
- `search_sessions` accepts `room` and `level` filters.

To add rooms: append rows to `data/rooms.csv`, then run `python scripts/validate_rooms.py` (add `--missing` to list sessions without a room).


## Strict day planning (no overlaps, limited lateness, lunch and networking)

- MCP tool `plan_strict_day` (REST `POST /agenda/plan`) picks the best-scoring sessions for your topics so that no two overlap and every move can be walked within `late_tolerance_minutes` (default 2). `lateness_basis` is `worst` (safe, default) or `best` (you hurry). It adds a 30-minute lunch in Hall G (window 12:00-14:00) and two 20-minute networking blocks in the Hub, and returns the moves (gap, walking range, minutes late), the best sessions it dropped with reasons, and warnings. The keynote and Hub talks are options (`include_keynote`, `include_hub_talks`).
- MCP tool `check_walk(from_place, to_place, gap_minutes)` checks a custom stop such as lunch. `check_transition` also returns `lateIfWalking`.
- Sessions in `data/not_in_app.csv` (not found in the mobile app) are flagged `inApp: false` and never planned. `data/session_overrides.csv` corrects dates and times taken from the app.
- All walking times are estimates; the Hub location is unconfirmed.

## Connecting it to Claude and ChatGPT (MCP, recommended)

Both clients connect to the same remote MCP endpoint: `https://YOUR-SERVICE.onrender.com/mcp` (no authentication; the data is public and every tool is read-only). The landing page at `/` shows this URL with a copy button.

**Claude.ai** — Settings → Connectors → Add custom connector → paste the URL.

**Claude Code**

```bash
claude mcp add --transport http ai-world https://YOUR-SERVICE.onrender.com/mcp
```

**Claude Desktop (local stdio)** — add to `claude_desktop_config.json`. Use the Python from the virtualenv where you ran `pip install -r requirements.txt`:

```json
{
  "mcpServers": {
    "ai-world-agenda": {
      "command": "/absolute/path/to/ai-world-agenda-plugin/.venv/bin/python",
      "args": ["-m", "app.mcp_server"],
      "cwd": "/absolute/path/to/ai-world-agenda-plugin"
    }
  }
}
```

**ChatGPT** — Settings → Connectors → Advanced → enable Developer mode, then create a connector with the URL above (no authentication).

Optional environment variables:

- `ALLOWED_HOSTS` — comma-separated hostnames (for example `YOUR-SERVICE.onrender.com`) to enable host validation on `/mcp`. Unset by default; a wrong value makes `/mcp` fail.
- `PUBLIC_URL` — public base URL used for the MCP icon and website URLs (default `https://ai-world-agenda-plugin.onrender.com`). Set it if your hostname differs.
- `AI_WORLD_DATA` — path to an alternate catalog JSON.
- `HOST`, `PORT` — bind address/port (`PORT` is set by Render).

## Connecting it to ChatGPT (legacy OpenAPI plugin/actions)

Only needed if your ChatGPT workspace still uses OpenAPI actions instead of MCP. Register `https://YOUR-SERVICE.onrender.com/openapi.yaml`.

`openapi.yaml` currently lists `https://ai-world-agenda-plugin.onrender.com` under `servers:`. If your Render service has a different hostname, update that entry. The plugin manifest at `/.well-known/ai-plugin.json` is generated from the incoming host, so it needs no edit. `localhost` is only for development; a hosted integration needs an HTTPS URL.

## Deploy on Render

The app binds to `0.0.0.0` and reads Render's `PORT` environment variable. The Starter plan is recommended: it is always on, while a free service spins down when idle and the first connector call can time out.

### Option A — Blueprint (`render.yaml`)

1. Push this project to a GitHub repository.
2. In Render, choose **New > Blueprint** and connect the repository.
3. Render creates the web service from `render.yaml` and deploys it.
4. Verify:

```text
https://YOUR-SERVICE.onrender.com/            (landing page)
https://YOUR-SERVICE.onrender.com/health
https://YOUR-SERVICE.onrender.com/openapi.yaml
```

### Option B — Manual Render Web Service

```text
Runtime: Python
Build command: pip install -r requirements.txt
Start command: uvicorn app.asgi:app --host 0.0.0.0 --port $PORT
Health check path: /health
Plan: Starter
Env: PYTHON_VERSION=3.12.7 (any 3.10+)
```

If you are upgrading an older deployment, push the new code first and then change the start command (the old `python -m app.server` only serves REST). No database, secret or persistent disk is required.

## Snapshot limitation

This catalog is not live. A session's time, room, capacity, speaker list, or title can change. The API exposes `GET /catalog/meta` (and the MCP tool `get_catalog_metadata`), and the assistant should always treat the official Oracle catalog as authoritative for final event logistics.

## Privacy/security

This project deliberately:

- does not include the original authenticated HTML snapshot (it is git-ignored);
- does not store Oracle passwords, cookies or SSO tokens;
- does not automate MFA or bypass Oracle access controls;
- exposes only read-only, public catalog data with no authentication.

## Next useful iteration

Add an authenticated **admin-only upload endpoint** that accepts a newly saved HTML snapshot, sanitizes it, rebuilds `sessions.json`, and discards the raw HTML. This would make refreshing the catalog easy without solving Oracle SSO.


## License

The code is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE). You may use, modify and share it for noncommercial purposes. Commercial use needs permission from the author.

The license covers the code and my own data files (`venue.json`, `not_in_app.csv`, `session_overrides.csv`). Session information in `data/sessions.json` and the room assignments in `data/rooms.csv` come from Oracle's public catalog and mobile app. Oracle's content is not covered by this license. The saved catalog pages and screenshots I used as sources are not published. This is an unofficial community project and is not affiliated with Oracle.

Author: Robert van Molken, Senior AI Solution Architect, Exoblock B.V.
