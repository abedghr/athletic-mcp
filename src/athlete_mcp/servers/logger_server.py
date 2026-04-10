"""MCP Server 1: Training Logger.

Exposes tools for logging workouts, sets, exercises, and bodyweight.
All tools call the FastAPI backend over HTTP.
"""

import logging
import sys

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from athlete_mcp.config import settings
from athlete_mcp.tools.logger_tools import (
    add_exercise,
    delete_set,
    edit_set,
    get_today,
    list_exercises,
    log_bodyweight,
    log_set,
    rate_workout,
    search_exercise,
    start_workout,
)

# Configure logging to stderr — MCP uses stdout for stdio transport, so any
# output on stdout would corrupt the JSON-RPC stream. WARNING is the safe
# default for stdio to minimize noise; override via LOG_LEVEL env var.
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.WARNING),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

mcp = FastMCP(
    "athlete-logger",
    stateless_http=True,
    json_response=True,
    # DNS rebinding protection is for localhost-only MCP servers. We expose this
    # over the public internet behind bearer auth, so the protection just blocks
    # legitimate requests with the wrong Host header (HTTP 421). Disable it.
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)


@mcp.tool()
async def tool_start_workout(
    title: str | None = None,
    bodyweight_kg: float | None = None,
    location: str | None = None,
    notes: str | None = None,
) -> str:
    """Start or retrieve today's training session.

    Creates a new workout for today or returns the existing one.
    Optionally set a session title, your bodyweight, gym location, and notes.
    """
    return await start_workout(title=title, bodyweight_kg=bodyweight_kg, location=location, notes=notes)


@mcp.tool()
async def tool_log_set(
    exercise: str,
    reps: int | None = None,
    duration_secs: int | None = None,
    distance_m: float | None = None,
    added_weight_kg: float = 0,
    bodyweight_kg: float | None = None,
    rpe: float | None = None,
    notes: str | None = None,
) -> str:
    """Log a single training set for any exercise.

    Accepts flexible exercise names — will fuzzy-match 'pull ups', 'straight bar', 'toes to bar', etc.
    Automatically links to today's workout session (creates one if none exists).
    For weighted exercises, provide added_weight_kg (external weight only — bodyweight tracked separately).
    For timed exercises like plank or L-sit, provide duration_secs instead of reps.
    Returns confirmation and alerts if a personal record was broken.
    """
    return await log_set(
        exercise=exercise, reps=reps, duration_secs=duration_secs,
        distance_m=distance_m, added_weight_kg=added_weight_kg,
        bodyweight_kg=bodyweight_kg, rpe=rpe, notes=notes,
    )


@mcp.tool()
async def tool_log_bodyweight(
    weight_kg: float,
    time_of_day: str = "morning",
    notes: str | None = None,
) -> str:
    """Log today's bodyweight measurement.

    Tracks bodyweight independently of workouts for monitoring weight trends.
    time_of_day: 'morning', 'evening', or 'post_workout'.
    """
    return await log_bodyweight(weight_kg=weight_kg, time_of_day=time_of_day, notes=notes)


@mcp.tool()
async def tool_get_today() -> str:
    """Get a full summary of today's training session.

    Shows all sets logged today, exercises performed, total volume, and session details.
    Creates a workout for today if one doesn't exist yet.
    """
    return await get_today()


@mcp.tool()
async def tool_add_exercise(
    name: str,
    display_name: str,
    category: str,
    tracking_type: str = "reps",
    is_weighted: bool = True,
    equipment: str | None = None,
    muscle_groups: str | None = None,
    description: str | None = None,
) -> str:
    """Add a new exercise to the catalog.

    The catalog is fully dynamic — add any exercise for any sport.
    name: slug format like 'pull_up', 'bench_press'
    display_name: human-readable like 'Pull Up', 'Bench Press'
    category: push|pull|core|legs|full_body|isometric|cardio|sport_specific
    tracking_type: reps|duration|distance|rounds
    """
    return await add_exercise(
        name=name, display_name=display_name, category=category,
        tracking_type=tracking_type, is_weighted=is_weighted,
        equipment=equipment, muscle_groups=muscle_groups, description=description,
    )


@mcp.tool()
async def tool_list_exercises(
    category: str | None = None,
    equipment: str | None = None,
) -> str:
    """List all available exercises in the catalog.

    Optionally filter by category (push, pull, core, legs, full_body, isometric, cardio)
    or equipment type (bodyweight, barbell, dumbbell, rings, bar, machine, none).
    """
    return await list_exercises(category=category, equipment=equipment)


@mcp.tool()
async def tool_edit_set(
    set_id: int,
    reps: int | None = None,
    duration_secs: int | None = None,
    distance_m: float | None = None,
    added_weight_kg: float | None = None,
    bodyweight_kg: float | None = None,
    rpe: float | None = None,
    notes: str | None = None,
) -> str:
    """Correct a previously logged set.

    Update any field of an existing set by its ID. Only provide the fields to change.
    Personal records are automatically re-evaluated after the edit.
    """
    return await edit_set(
        set_id=set_id, reps=reps, duration_secs=duration_secs,
        distance_m=distance_m, added_weight_kg=added_weight_kg,
        bodyweight_kg=bodyweight_kg, rpe=rpe, notes=notes,
    )


@mcp.tool()
async def tool_delete_set(set_id: int) -> str:
    """Remove a set from today's session (soft delete).

    The set is marked as deleted but not permanently removed.
    Personal records are automatically re-evaluated.
    """
    return await delete_set(set_id=set_id)


@mcp.tool()
async def tool_rate_workout(
    rating: int,
    notes: str | None = None,
    duration_mins: int | None = None,
) -> str:
    """Rate today's training session on a 1-5 scale.

    1 = terrible, 2 = poor, 3 = average, 4 = good, 5 = excellent.
    Optionally add notes about how the session felt and total duration in minutes.
    """
    return await rate_workout(rating=rating, notes=notes, duration_mins=duration_mins)


@mcp.tool()
async def tool_search_exercise(query: str) -> str:
    """Search for an exercise by name.

    Uses fuzzy matching to find exercises. Returns ranked matches with similarity scores.
    Useful when you're not sure of the exact exercise name.
    """
    return await search_exercise(query=query)


# ---------------------------------------------------------------------------
# Prompts — show up as /slash commands or suggested actions in Claude UI.
# ---------------------------------------------------------------------------

@mcp.prompt()
def start_session(bodyweight_kg: float | None = None) -> str:
    """Start today's training session and see what's already logged."""
    bw = f" My bodyweight is {bodyweight_kg}kg." if bodyweight_kg else ""
    return f"Start my workout session.{bw} Show me what's already logged today."


@mcp.prompt()
def log_exercise(exercise: str, sets: int = 1, reps: int = 8, weight_kg: float = 0) -> str:
    """Quick-log sets for an exercise."""
    w = f" with {weight_kg}kg added" if weight_kg else ""
    return f"Log {sets} sets of {exercise}, {reps} reps each{w}."


@mcp.prompt()
def end_session(rating: int = 4) -> str:
    """Wrap up today's workout with a rating and summary."""
    return f"Rate today's workout {rating}/5. Show me a full summary of everything I did today."


@mcp.prompt()
def quick_summary() -> str:
    """See today's session at a glance."""
    return "Show me today's training session — exercises, sets, volume, PRs."


def get_http_app():
    """Return the ASGI app for mounting into FastAPI (stateless HTTP transport)."""
    return mcp.streamable_http_app()


def main():
    """Run as a standalone stdio MCP server (used by Claude Desktop locally)."""
    logger.info("Starting athlete-logger MCP server (stdio)...")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
