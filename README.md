# Athletic Training MCP System

A personal athletic performance tracker exposed to Claude as two MCP servers, backed by a FastAPI + Turso (cloud SQLite) API. Deployed on Render. Works from Claude desktop, web, and mobile via Custom Connectors.

Designed for any sport — calisthenics, barbell, cardio. The exercise catalog is fully dynamic.

## Quick links

- **Deployed URL:** `https://athlete-mcp.onrender.com` (replace with yours)
- **Architecture, API reference, DB schema:** see [DOCS.md](DOCS.md)
- **System prompt for Claude:** see [CLAUDE_SYSTEM_PROMPT.md](CLAUDE_SYSTEM_PROMPT.md)

## Architecture (one-line)

```
Claude (web/mobile/desktop) ──HTTPS──► Render (FastAPI + MCP-over-HTTP) ──libsql──► Turso
```

Single Python process:
- **FastAPI REST API** — `/exercises`, `/workouts`, `/sets`, `/analytics` (bearer-auth protected)
- **Two mounted MCP HTTP servers** — `/mcp/{secret}/logger/mcp` and `/mcp/{secret}/analytics/mcp` (URL-secret protected)
- **18 MCP tools total** (10 logger + 8 analytics) — expose the REST API to Claude

## Prerequisites

- Python 3.11+
- A [Turso](https://turso.tech) account (free)
- A [Render](https://render.com) account (free)
- Claude **Pro** (or higher) — required for Custom Connectors
- Docker (optional, for local container testing)

## Local development

```bash
# Install
pip install -e .

# Set env vars (or create a .env from .env.example)
export TURSO_DATABASE_URL=libsql://your-db.turso.io
export TURSO_AUTH_TOKEN=eyJ...
export MCP_API_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")

# Run the API (also serves the MCP HTTP endpoints)
python scripts/run_api.py

# Run the integration test against your local instance
MCP_TEST_MODE=http MCP_API_KEY=$MCP_API_KEY python3 scripts/test_mcp_integration.py
```

The API will be at `http://localhost:8000`. Swagger UI at `http://localhost:8000/docs`.

## Deploy to Render

1. Push this repo to GitHub
2. In Render → **New → Blueprint** → connect your fork
3. Render reads `render.yaml` and creates the service
4. Set 3 secret env vars in the Render dashboard:
   - `TURSO_DATABASE_URL` — from Turso dashboard
   - `TURSO_AUTH_TOKEN` — from Turso dashboard
   - `MCP_API_KEY` — generate with `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`
5. Wait for the build (~2 min). When you see `Application startup complete` in the logs, you're live.

## Connect to Claude

In Claude → **Settings → Connectors → Add custom connector** (twice):

| Name | Remote MCP server URL |
|---|---|
| Athlete Logger | `https://YOUR-APP.onrender.com/mcp/YOUR-MCP-API-KEY/logger/mcp` |
| Athlete Analytics | `https://YOUR-APP.onrender.com/mcp/YOUR-MCP-API-KEY/analytics/mcp` |

Leave OAuth fields blank. The API key is in the URL itself (capability URL pattern).

⚠️ **Treat the full URL as a password.** Anyone with it can write to your training database. Rotate `MCP_API_KEY` in Render env vars if you ever leak the URL.

## Test it

In any Claude chat (web, desktop, or mobile):

> log 5 pull ups with 3kg added weight

Claude calls `tool_log_set` and confirms. Open the Turso dashboard to see the row in real time.

> what's my pull up PR?

Claude calls `tool_get_prs("pull_up")` and tells you.

## Local stdio mode (optional, fallback)

If you want to run everything locally without going through the cloud — useful for development or air-gapped use — see [DOCS.md](DOCS.md#local-stdio-mode) for how to configure Claude Desktop with the `mcpServers` block.

## Project layout

```
athletic/
├── README.md                      ← you are here
├── DOCS.md                        ← architecture, API reference, schema
├── CLAUDE_SYSTEM_PROMPT.md        ← paste into Claude custom instructions
├── pyproject.toml
├── Dockerfile                     ← for Render
├── render.yaml                    ← Render blueprint
├── .env.example
├── claude_desktop_config_snippet.json   ← optional local stdio template
├── src/athlete_mcp/
│   ├── config.py                  ← env-driven settings
│   ├── database/                  ← libsql connection + schema
│   ├── api/                       ← FastAPI app, routers, schemas, auth
│   ├── servers/                   ← FastMCP servers (logger + analytics)
│   └── tools/                     ← MCP tool implementations + httpx client
└── scripts/
    ├── run_api.py                 ← start the FastAPI/MCP server
    ├── run_logger.py              ← stdio MCP logger (local only)
    ├── run_analytics.py           ← stdio MCP analytics (local only)
    └── test_mcp_integration.py    ← end-to-end test (stdio + http modes)
```
