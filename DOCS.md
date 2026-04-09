# Athletic Training MCP — Technical Documentation

Single-document reference for the architecture, REST API, MCP tools, database schema, configuration, and security model.

---

## Table of contents

1. [Architecture](#architecture)
2. [Request flow (end-to-end)](#request-flow)
3. [Configuration (env vars)](#configuration)
4. [Database schema](#database-schema)
5. [REST API reference](#rest-api-reference)
6. [MCP tools reference](#mcp-tools-reference)
7. [Security model](#security-model)
8. [Local stdio mode](#local-stdio-mode)
9. [Operations](#operations)

---

## Architecture

Single FastAPI process running on Render. It serves three things over the same port:

```
                                Render (single Python process, port $PORT)
                                ┌─────────────────────────────────────────────┐
                                │                                             │
Claude (web/iOS/Android) ──HTTPS┼──► /mcp/{secret}/logger/mcp     ─┐          │
                                │                                  ├─► MCP    │
                                │    /mcp/{secret}/analytics/mcp  ─┘ tools    │
                                │                                     │       │
                                │                                     │ httpx │
                                │                                     ▼       │
You (curl, integration test) ───┼──► /exercises  /workouts  /sets  /analytics │
                                │       (REST, bearer-auth protected)         │
                                │                                     │       │
                                │                                     │ libsql│
                                └─────────────────────────────────────┼───────┘
                                                                      │
                                                            ┌─────────▼─────────┐
                                                            │  Turso (cloud     │
                                                            │  SQLite, libsql)  │
                                                            └───────────────────┘
```

**Why one process instead of three?** Originally the design was 3 processes (FastAPI + 2 stdio MCP servers). On Render's free tier, that's wasteful — each Python process eats ~50MB RAM, and the free tier has 512MB. Mounting the MCP HTTP apps inside the same FastAPI process drops memory to ~120MB total.

**Why does the MCP layer call the REST API via HTTP loopback (instead of direct function calls)?** Because the same MCP tool code runs in two modes:

1. **Stdio mode (local Claude Desktop)** — MCP server is its own process, calls FastAPI on `localhost:8000`
2. **HTTP mode (remote Claude)** — MCP server is mounted inside FastAPI, calls FastAPI on `localhost:$PORT` (loopback to itself)

In both modes, [`tools/shared.py:get_client()`](src/athlete_mcp/tools/shared.py) builds an httpx client pointed at `settings.API_BASE_URL`. The difference is just the URL. Zero code change between modes.

---

## Request flow

End-to-end trace of a single message: *"log 10 pull ups with 5kg"*

```
1. You type the message in Claude (mobile/web/desktop)
       │
       ▼
2. Claude client → HTTPS → api.anthropic.com
       │ (your message + 18 cached tool definitions)
       ▼
3. Claude (the model) on Anthropic GPUs
       │ Decides to call tool_log_set
       │ Returns: tool_use { name: "tool_log_set",
       │                     input: { exercise: "pull_up", reps: 10, added_weight_kg: 5 } }
       ▼
4. api.anthropic.com → HTTPS POST → https://athlete-mcp.onrender.com/mcp/{secret}/logger/mcp
       │ JSON-RPC: { method: "tools/call", params: {...} }
       ▼
5. Render's edge → your Docker container (FastAPI + uvicorn)
       │
       ▼
6. Starlette routing matches /mcp/{secret}/logger mount
       │ FastMCP receives the JSON-RPC, looks up tool_log_set in its registry
       │ Calls the decorated async function
       ▼
7. servers/logger_server.py: tool_log_set(...)
       │
       ▼
8. tools/logger_tools.py: log_set(...)
       │ Builds payload, calls safe_api_call("post", "/sets", json=payload)
       ▼
9. tools/shared.py: safe_api_call(...)
       │ httpx client created with base_url=localhost:$PORT
       │ Auto-injects Authorization: Bearer $MCP_API_KEY (because we're hitting REST)
       │ POST http://localhost:$PORT/sets → loops back through uvicorn into the same process
       ▼
10. api/auth.py: BearerAuthMiddleware
       │ Sees /sets path → checks Authorization header → matches → passes through
       ▼
11. api/routers/sets.py: log_set(set_data, db)
       │ Resolves "pull_up" via api/dependencies.py: resolve_exercise()
       │ Gets/creates today's workout
       │ Auto-numbers the set
       │ Inserts into sets table
       │ Calls update_personal_records() → upserts personal_records table
       │ Returns SetResponse with new_pr field if a record was beaten
       ▼
12. database/connection.py: Database (libsql wrapper)
       │ Executes SQL via libsql_client → HTTPS to Turso
       ▼
13. Turso (cloud SQLite) writes the row, returns the new ID
       │
       ▲
14. Response bubbles back up:
       │ Turso → Database → router → Pydantic → JSON → httpx → log_set() → format_tool_response()
       │ → returns a JSON string to FastMCP
       │
       ▼
15. FastMCP wraps the string as MCP content, writes to HTTP response
       │ { jsonrpc: "2.0", result: { content: [{ type: "text", text: "{...}" }] } }
       │
       ▲
16. Anthropic receives the tool_result, Claude generates natural language:
       │ "Logged set 1 of Pull Up: 10 reps, +5kg. NEW PR — volume: 50.0kg!"
       │
       ▼
17. You see it in the chat
```

---

## Configuration

All config is via env vars (read by [`src/athlete_mcp/config.py`](src/athlete_mcp/config.py)). Set them in Render dashboard for production, or in `.env` locally.

| Variable | Required? | Default | Purpose |
|---|---|---|---|
| `TURSO_DATABASE_URL` | Yes (production) | none | Turso libsql URL. Auto-converted from `libsql://` to `https://`. |
| `TURSO_AUTH_TOKEN` | Yes (production) | none | Turso JWT auth token. |
| `MCP_API_KEY` | Yes (production) | none | Bearer token for REST + URL-secret segment for MCP. |
| `ATHLETE_DB_PATH` | No | `~/.athlete/training.db` | Local SQLite file path (used only when Turso vars not set). |
| `ATHLETE_API_HOST` | No | `0.0.0.0` | Host to bind. |
| `ATHLETE_API_PORT` | No | `$PORT` or `8000` | Port to bind. Render injects `PORT`. |
| `ATHLETE_API_BASE_URL` | No | `http://localhost:$PORT` | Loopback URL the MCP tools use. Override only for cross-process setups. |
| `LOG_LEVEL` | No | `INFO` | Python logging level. Use `WARNING` in stdio mode to keep stdout clean. |
| `ATHLETE_DEV` | No | `0` | Set to `1` to enable uvicorn auto-reload. |

**Local-only fallback:** if `TURSO_DATABASE_URL` is unset, the app uses local SQLite at `ATHLETE_DB_PATH`. Useful for offline dev.

---

## Database schema

Defined in [`src/athlete_mcp/database/migrations.py`](src/athlete_mcp/database/migrations.py). All tables have soft-delete via `deleted_at TIMESTAMP NULL`. All queries filter `WHERE deleted_at IS NULL`.

### `exercises` — the dynamic exercise catalog
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | autoincrement |
| `name` | TEXT UNIQUE | slug like `pull_up`, `bench_press` |
| `display_name` | TEXT | human-readable: `Pull Up` |
| `category` | TEXT | `push`, `pull`, `core`, `legs`, `full_body`, `isometric`, `cardio`, `sport_specific` |
| `muscle_groups` | TEXT (JSON) | optional, e.g. `["chest","triceps"]` |
| `equipment` | TEXT | `bodyweight`, `barbell`, `dumbbell`, `rings`, `bar`, `machine`, `none` |
| `tracking_type` | TEXT | `reps`, `duration`, `distance`, `rounds` |
| `is_weighted` | BOOLEAN | can external weight be added? |
| `weight_unit` | TEXT | `kg` or `lbs` |
| `description` | TEXT | optional |
| `created_at`, `updated_at`, `deleted_at` | TIMESTAMP | audit + soft delete |

**Seeded with 26 default exercises** on first migration (calisthenics, barbell, cardio).

### `workouts` — training sessions
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | autoincrement |
| `date` | TEXT | `YYYY-MM-DD`, one workout per day expected |
| `title` | TEXT | optional session label |
| `bodyweight_kg` | REAL | bodyweight at start of session |
| `location` | TEXT | gym name, outdoor, etc. |
| `notes` | TEXT | |
| `rating` | INTEGER 1-5 | how the session felt |
| `duration_mins` | INTEGER | total session duration |
| `created_at`, `updated_at`, `deleted_at` | TIMESTAMP | |

### `sets` — individual sets / efforts
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `workout_id` | INTEGER FK → workouts | CASCADE on delete |
| `exercise_id` | INTEGER FK → exercises | |
| `exercise_name` | TEXT | denormalized slug (resilient against catalog edits) |
| `exercise_display_name` | TEXT | denormalized display name |
| `set_number` | INTEGER | 1-indexed within (workout, exercise), auto-assigned |
| `reps` | INTEGER | for reps-tracked exercises |
| `duration_secs` | INTEGER | for timed exercises (plank, L-sit) |
| `distance_m` | REAL | for distance-tracked (run, row) |
| `bodyweight_kg` | REAL | athlete bodyweight at time of set |
| `added_weight_kg` | REAL | external weight (belt, vest, barbell) — NOT bodyweight |
| `rpe` | REAL 1-10 | rate of perceived exertion |
| `notes` | TEXT | |
| `created_at`, `updated_at`, `deleted_at` | TIMESTAMP | |

**Computed (not stored):**
- `total_weight_kg` = `bodyweight_kg + added_weight_kg`
- `volume_kg` = `reps × total_weight_kg`

### `personal_records` — denormalized PR cache
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `exercise_id` | INTEGER FK | |
| `exercise_name` | TEXT | denormalized |
| `pr_type` | TEXT | `reps`, `weight`, `volume`, `duration`, `distance` |
| `value` | REAL | the PR value |
| `set_id` | INTEGER FK | the set that set the PR |
| `date_achieved` | TEXT | `YYYY-MM-DD` |
| `previous_value` | REAL | for "improved by X" messaging |
| `improvement_pct` | REAL | computed |
| `created_at` | TIMESTAMP | |

**UNIQUE(exercise_name, pr_type)** — one record per exercise per PR type. Updated by [`update_personal_records()`](src/athlete_mcp/api/routers/sets.py) on every set insert/update/delete.

### `bodyweight_log` — standalone bodyweight tracking
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `date` | TEXT UNIQUE | one entry per day |
| `weight_kg` | REAL | |
| `time_of_day` | TEXT | `morning`, `evening`, `post_workout` |
| `notes` | TEXT | |
| `created_at` | TIMESTAMP | |

### `schema_migrations` — migration tracking
| Column | Type |
|---|---|
| `version` | INTEGER PK |
| `name` | TEXT |
| `applied_at` | TIMESTAMP |

---

## REST API reference

All endpoints except `/health`, `/ready`, `/docs`, `/openapi.json` require:
```
Authorization: Bearer $MCP_API_KEY
```

Base URL (production): `https://athlete-mcp.onrender.com`

### Health
| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness check. Returns `{"status":"ok"}`. |
| GET | `/ready` | Readiness check. Returns `{"status":"ready"}`. |

### Exercises
| Method | Path | Description |
|---|---|---|
| GET | `/exercises` | List all (filter by `?category=`, `?equipment=`, `?tracking_type=`). |
| POST | `/exercises` | Create. Body: `ExerciseCreate`. 409 if name exists. |
| GET | `/exercises/{name}` | Get one (fuzzy resolved). |
| PATCH | `/exercises/{name}` | Update. Body: `ExerciseUpdate`. |
| DELETE | `/exercises/{name}` | Soft delete. |
| GET | `/exercises/search/{query}` | Fuzzy search, returns ranked matches. |

### Workouts
| Method | Path | Description |
|---|---|---|
| GET | `/workouts` | List (filter by `?date_from=`, `?date_to=`, `?limit=`). |
| POST | `/workouts` | Create new workout. |
| GET | `/workouts/today` | Get or create today's workout (idempotent). |
| GET | `/workouts/{id}` | Get workout with all its sets, computed totals. |
| PATCH | `/workouts/{id}` | Update workout (rating, notes, etc.). |
| DELETE | `/workouts/{id}` | Soft delete workout AND its sets. |

### Sets
| Method | Path | Description |
|---|---|---|
| POST | `/sets` | Log a new set. Auto-numbers, auto-resolves exercise, fires PR check. |
| GET | `/sets/{id}` | Get one. |
| PATCH | `/sets/{id}` | Edit. PRs re-evaluated. |
| DELETE | `/sets/{id}` | Soft delete. PRs re-evaluated. |
| GET | `/sets/workout/{workout_id}` | All sets for a workout. |

### Analytics
| Method | Path | Description |
|---|---|---|
| GET | `/analytics/prs` | All PRs (or `?exercise=`). |
| GET | `/analytics/prs/{exercise}` | PRs for one exercise. |
| GET | `/analytics/weekly-summary` | This week stats + delta vs last week (`?week_offset=` for past weeks). |
| GET | `/analytics/exercise/{name}/history` | Session-by-session history. |
| GET | `/analytics/exercise/{name}/stats` | Aggregate stats over `?period_days=`. |
| GET | `/analytics/plateaus` | Plateau detection (`?window_weeks=`, `?threshold_pct=`). |
| GET | `/analytics/frequency` | Training frequency by exercise + category. |
| GET | `/analytics/bodyweight` | Bodyweight history + trend. |
| POST | `/analytics/bodyweight?weight_kg=X` | Log bodyweight (upserts on date). |
| GET | `/analytics/volume-trend` | Weekly volume over `?weeks=`. |

**Interactive docs:** visit `https://YOUR-APP.onrender.com/docs` (Swagger UI). Note: you need to add `Authorization: Bearer ...` in the **Authorize** dialog at the top, otherwise every request returns 401.

---

## MCP tools reference

The MCP tools are 1:1 wrappers around the REST API. Each tool calls one (sometimes two) endpoints and formats the result as a natural-language sentence Claude can use directly.

**MCP endpoint URLs (production):**
- Logger: `https://YOUR-APP.onrender.com/mcp/$MCP_API_KEY/logger/mcp`
- Analytics: `https://YOUR-APP.onrender.com/mcp/$MCP_API_KEY/analytics/mcp`

### Logger tools (10) — [`src/athlete_mcp/tools/logger_tools.py`](src/athlete_mcp/tools/logger_tools.py)

| Tool | Calls | Purpose |
|---|---|---|
| `tool_start_workout` | GET `/workouts/today` (+ optional PATCH) | Start or fetch today's session, optionally set bodyweight/title/location |
| `tool_log_set` | POST `/sets` | Log a single set — fuzzy exercise match, auto-numbering, PR check |
| `tool_log_bodyweight` | POST `/analytics/bodyweight` | Standalone bodyweight entry |
| `tool_get_today` | GET `/workouts/today` | Full summary of today's session |
| `tool_add_exercise` | POST `/exercises` | Add a new exercise to the catalog |
| `tool_list_exercises` | GET `/exercises` | List catalog (filterable) |
| `tool_edit_set` | PATCH `/sets/{id}` | Correct a previously logged set |
| `tool_delete_set` | DELETE `/sets/{id}` | Soft delete a set |
| `tool_rate_workout` | GET `/workouts/today` + PATCH `/workouts/{id}` | Rate today's workout 1-5 |
| `tool_search_exercise` | GET `/exercises/search/{query}` | Fuzzy search by name |

### Analytics tools (8) — [`src/athlete_mcp/tools/analytics_tools.py`](src/athlete_mcp/tools/analytics_tools.py)

| Tool | Calls | Purpose |
|---|---|---|
| `tool_get_prs` | GET `/analytics/prs[/{exercise}]` | Personal records, all or per exercise |
| `tool_weekly_summary` | GET `/analytics/weekly-summary` | This week vs last week |
| `tool_exercise_history` | GET `/analytics/exercise/{name}/history` | Session-by-session log |
| `tool_exercise_stats` | GET `/analytics/exercise/{name}/stats` | Aggregate stats over N days |
| `tool_detect_plateau` | GET `/analytics/plateaus` | Find stalled exercises with suggested actions |
| `tool_training_frequency` | GET `/analytics/frequency` | How often each exercise/category trained |
| `tool_bodyweight_trend` | GET `/analytics/bodyweight` | Bodyweight history + trend |
| `tool_volume_trend` | GET `/analytics/volume-trend` | Weekly volume over time |

---

## Security model

There are **two distinct surfaces** with different protection:

### REST API (`/exercises`, `/workouts`, `/sets`, `/analytics`)
- **Bearer auth** via [`api/auth.py:BearerAuthMiddleware`](src/athlete_mcp/api/auth.py)
- Requires `Authorization: Bearer $MCP_API_KEY` header
- Public paths exempt: `/health`, `/ready`, `/docs`, `/openapi.json`
- **Used by:** the integration test, you with curl, future web/mobile UIs
- **Auth bypassed for `/mcp/*` paths** because they have a different protection model (below)

### MCP HTTP transport (`/mcp/{secret}/logger/mcp`, `/mcp/{secret}/analytics/mcp`)
- **Capability URL** — the `MCP_API_KEY` is embedded in the URL path
- Anyone hitting `/mcp/wrong-secret/...` gets a 404 from Starlette's router (the mount doesn't exist for the wrong path)
- **Why not bearer auth?** Claude's Custom Connector UI only supports OAuth 2.0, not arbitrary headers. Implementing OAuth would be ~200 lines of new code (discovery, authorize, token, refresh, PKCE) for the same effective security.
- **Same model as Slack incoming webhooks, Google Calendar private iCal feeds, Trello board private RSS URLs** — battle-tested for personal tools.

### One key, two uses
`MCP_API_KEY` plays both roles:
1. **Path segment** in the MCP URL (URL-secret protection for Claude)
2. **Bearer token** for REST API (header protection for everything else)

The in-process MCP→REST loopback uses the bearer flavor — [`tools/shared.py:get_client()`](src/athlete_mcp/tools/shared.py) auto-injects the header so the MCP tool implementations don't need to know about auth.

### Rotation
If you ever leak the URL or token:
1. Render dashboard → service → Environment → edit `MCP_API_KEY` → save
2. Render redeploys (~1 min) — the old URL stops working immediately
3. Update both connectors in Claude with the new URL

### What attackers can/can't do
- **Read your training data** — yes, if they have the URL
- **Write fake data** — yes, if they have the URL
- **Read your Turso token** — no, lives only in Render env vars
- **Pivot to other infrastructure** — no, the API doesn't expose credentials or shell
- **Cause data loss** — soft deletes only (deleted_at column), no hard deletes anywhere

---

## Local stdio mode

Optional. Useful if you want to run everything offline or develop without the cloud.

### Setup

1. Install locally: `pip install -e .`
2. Start the API: `python scripts/run_api.py` (or `bash scripts/start.sh`)
3. Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "athlete-logger": {
      "command": "/usr/local/bin/python3",
      "args": ["/ABSOLUTE/PATH/TO/athletic/scripts/run_logger.py"],
      "env": {
        "ATHLETE_API_BASE_URL": "http://localhost:8000",
        "LOG_LEVEL": "WARNING"
      }
    },
    "athlete-analytics": {
      "command": "/usr/local/bin/python3",
      "args": ["/ABSOLUTE/PATH/TO/athletic/scripts/run_analytics.py"],
      "env": {
        "ATHLETE_API_BASE_URL": "http://localhost:8000",
        "LOG_LEVEL": "WARNING"
      }
    }
  }
}
```

4. Quit Claude Desktop completely (⌘Q) and reopen.

In this mode the MCP tools are stdio-spoken with the Python subprocesses, and they call your local API instead of the deployed one.

### Caveats

- Only works on Claude Desktop (not web, not mobile)
- Requires the API server to be running before you open Claude
- If you have BOTH the local stdio config AND the cloud Custom Connectors enabled, Claude sees them as two separate sets of tools — they'll have the same names which can confuse the model. Pick one.

---

## Operations

### Cold starts (Render free tier)

The free tier sleeps the container after ~15 minutes of no traffic. The first request after sleep takes 30-60 seconds while the container reboots. To prevent this:

- **Free workaround:** set up a cron-like ping (cron-job.org, UptimeRobot — both free) to hit `https://YOUR-APP.onrender.com/health` every 10 minutes
- **Paid workaround:** upgrade to Render's Starter plan ($7/mo)

### Logs

Render dashboard → your service → **Logs** tab. Live tail of the running container. Look for:
- `Application startup complete` — service is ready
- `MCP HTTP transports ready` — both MCP mounts are alive
- `[INFO] athlete_mcp.api.auth` warnings — auth misconfiguration
- 401/404 spam — someone probing your URLs

### Metrics

Render shows CPU/memory/bandwidth on the **Metrics** tab. The free tier has:
- 512 MB RAM (you'll use ~120 MB)
- 100 GB egress/month (each tool call is a few KB — effectively unlimited)
- Sleeps after 15 min idle

### Backups

Turso has its own backup story (point-in-time recovery on paid plans). For free-tier safety:
- Periodically export with `turso db shell <name> .dump > backup.sql`
- Or just take a SQL dump via curl through the REST API

### Updating the deployment

```bash
git add -A && git commit -m "..." && git push
```

Render auto-deploys on push to `main`. ~2 min build + ~10 sec rolling restart. Your data lives in Turso, not the container, so deploys never lose data.

### Rolling back

Render keeps the last few deploys. **Manual deploy** dropdown → pick a previous commit → **Redeploy**.

### Running the integration test

```bash
# Against the deployed instance
MCP_TEST_MODE=http \
ATHLETE_API_BASE_URL=https://YOUR-APP.onrender.com \
MCP_API_KEY=your-key \
python3 scripts/test_mcp_integration.py

# Against a local instance
MCP_TEST_MODE=http \
MCP_API_KEY=any-key-matching-local-env \
python3 scripts/test_mcp_integration.py
```
