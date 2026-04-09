# Athletic Training MCP System

A production-grade athletic training tracker exposed as two MCP servers backed by a FastAPI + SQLite API.

Designed for serious athletes — calisthenics, barbell, cardio, anything. The exercise catalog is fully dynamic.

## Architecture

```
Claude Desktop
    │
    ├── MCP stdio → athlete-logger     ─────┐
    │                                        ├──► FastAPI (localhost:8000) ──► SQLite (WAL)
    └── MCP stdio → athlete-analytics  ─────┘
```

- **FastAPI** owns all business logic, validation, and DB access
- **MCP servers** are thin HTTP adapters — each tool calls the API via httpx
- **SQLite** with WAL mode, foreign keys, soft deletes
- The API is independently usable (curl, scripts, future UIs)

## Prerequisites

- Python 3.11+
- pip

## Installation

```bash
git clone <this repo>
cd athletic
pip install -e .

# Optional: configure env vars
cp .env.example .env
# Edit .env to set ATHLETE_DB_PATH, DEFAULT_BODYWEIGHT_KG, etc.
```

## Running the System

You need three terminals running simultaneously.

**Terminal 1 — FastAPI server (must be started first):**
```bash
python scripts/run_api.py
```
This creates the SQLite DB, runs migrations, seeds default exercises.
Visit http://localhost:8000/docs for the Swagger UI.

**Terminal 2 — Logger MCP server:**
```bash
python scripts/run_logger.py
```

**Terminal 3 — Analytics MCP server:**
```bash
python scripts/run_analytics.py
```

## Claude Desktop Setup

1. Open your Claude Desktop config:
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`

2. Merge the contents of `claude_desktop_config_snippet.json` into your config, updating the `cwd` path to the absolute path of this project.

3. **Important:** Start the FastAPI server (`python scripts/run_api.py`) **before** opening Claude Desktop. Otherwise the MCP tools will return `API_UNAVAILABLE` errors.

4. Restart Claude Desktop. You should see the `athlete-logger` and `athlete-analytics` tools available.

## Example Conversations

Once configured, you can talk to Claude naturally:

> "Start today's workout, I weigh 82kg today"
> → calls `tool_start_workout(bodyweight_kg=82)`

> "Log 10 pull ups with 5kg added weight"
> → calls `tool_log_set(exercise="pull ups", reps=10, added_weight_kg=5)`

> "Log a 45 second L-sit"
> → calls `tool_log_set(exercise="l sit", duration_secs=45)`

> "What are my PRs?"
> → calls `tool_get_prs()`

> "How did this week compare to last week?"
> → calls `tool_weekly_summary()`

> "Am I plateauing on anything?"
> → calls `tool_detect_plateau()`

> "Show me my pull up progression over the last 3 months"
> → calls `tool_exercise_history(exercise="pull up", limit=50)`

## Adding a New Exercise

You can add exercises two ways:

**Via Claude:**
> "Add a new exercise called human flag, it's a core exercise, isometric, tracked by duration, no external weight"

**Directly via API:**
```bash
curl -X POST http://localhost:8000/exercises \
  -H "Content-Type: application/json" \
  -d '{
    "name": "human_flag",
    "display_name": "Human Flag",
    "category": "core",
    "tracking_type": "duration",
    "is_weighted": false,
    "equipment": "bar"
  }'
```

## Database Location

By default, the SQLite database lives at `~/.athlete/training.db`. Override with the `ATHLETE_DB_PATH` environment variable.

**Backup:** just copy the file.
```bash
cp ~/.athlete/training.db ~/.athlete/training.db.backup
```

## FastAPI Interactive Docs

Visit http://localhost:8000/docs for the Swagger UI with every endpoint documented and testable in-browser.

## Troubleshooting

**MCP tools return `API_UNAVAILABLE`:**
The FastAPI server isn't running. Start it with `python scripts/run_api.py` before using Claude Desktop.

**Exercise not found:**
The tool response will include suggestions — try one of those, or add the exercise first with `tool_add_exercise`.

**Database locked:**
SQLite WAL mode should prevent most locks, but if it happens, ensure only one FastAPI instance is running. Check with `lsof ~/.athlete/training.db`.

**Tools don't appear in Claude Desktop:**
Check the logs — Claude Desktop shows MCP server stderr in its developer console. Common issues: wrong `cwd` path, missing dependencies, Python version mismatch.

## Project Structure

```
athletic/
├── pyproject.toml
├── README.md
├── .env.example
├── claude_desktop_config_snippet.json
├── src/athlete_mcp/
│   ├── config.py
│   ├── database/
│   │   ├── connection.py
│   │   ├── migrations.py
│   │   └── models.py
│   ├── api/
│   │   ├── main.py
│   │   ├── dependencies.py
│   │   ├── routers/       # health, exercises, workouts, sets, analytics
│   │   └── schemas/       # Pydantic request/response models
│   ├── servers/
│   │   ├── logger_server.py
│   │   └── analytics_server.py
│   └── tools/
│       ├── shared.py      # httpx client, safe_api_call, fuzzy helpers
│       ├── logger_tools.py
│       └── analytics_tools.py
└── scripts/
    ├── run_api.py
    ├── run_logger.py
    └── run_analytics.py
```
