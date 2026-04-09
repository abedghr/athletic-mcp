"""MCP Server 2: Performance Analytics.

Exposes tools for analyzing training data, tracking PRs, detecting plateaus.
All tools call the FastAPI backend over HTTP.
"""

import logging
import sys

from mcp.server.fastmcp import FastMCP

from athlete_mcp.config import settings
from athlete_mcp.tools.analytics_tools import (
    bodyweight_trend,
    detect_plateau,
    exercise_history,
    exercise_stats,
    get_prs,
    training_frequency,
    volume_trend,
    weekly_summary,
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
    "athlete-analytics",
    stateless_http=True,
    json_response=True,
)


@mcp.tool()
async def tool_get_prs(exercise: str | None = None) -> str:
    """Get personal records — all exercises or a specific one.

    Shows your best performances: max reps, max weight, max volume, max duration.
    Includes when each PR was set and how many days ago.
    Leave exercise blank for all PRs, or specify an exercise name (fuzzy matched).
    """
    return await get_prs(exercise=exercise)


@mcp.tool()
async def tool_weekly_summary(week_offset: int = 0) -> str:
    """Get a training summary for this week or a past week.

    Shows total sessions, sets, reps, volume, unique exercises, and average RPE.
    Includes day-by-day breakdown and comparison deltas vs the previous week.
    week_offset: 0 = this week, -1 = last week, -2 = two weeks ago.
    """
    return await weekly_summary(week_offset=week_offset)


@mcp.tool()
async def tool_exercise_history(exercise: str, limit: int = 20) -> str:
    """Get session-by-session history for a specific exercise.

    Shows every training session where you performed this exercise, with full details:
    sets, reps, weights, volume, and RPE per session. Useful for tracking progression.
    """
    return await exercise_history(exercise=exercise, limit=limit)


@mcp.tool()
async def tool_exercise_stats(exercise: str, period_days: int = 30) -> str:
    """Get aggregate stats for an exercise over a time period.

    Shows total sessions, sets, reps, volume, max weight, averages, and trend direction
    (improving, stable, or declining) over the specified number of days.
    """
    return await exercise_stats(exercise=exercise, period_days=period_days)


@mcp.tool()
async def tool_detect_plateau(window_weeks: int = 4, threshold_pct: float = 5.0) -> str:
    """Find exercises where progress has stalled.

    Analyzes training data over the specified window. Compares first half vs second half
    of the window period. Returns three lists: plateaued (with suggested actions),
    improving, and insufficient data. threshold_pct sets the minimum improvement
    to not be considered plateaued (default 5%).
    """
    return await detect_plateau(window_weeks=window_weeks, threshold_pct=threshold_pct)


@mcp.tool()
async def tool_training_frequency(period_days: int = 30) -> str:
    """Show how often each exercise and category is trained.

    Displays per-exercise session counts, total sets, last performed date, and days since.
    Also shows frequency breakdown by category (push, pull, core, legs, etc.).
    Useful for spotting imbalances in training.
    """
    return await training_frequency(period_days=period_days)


@mcp.tool()
async def tool_bodyweight_trend(limit: int = 30) -> str:
    """Get your bodyweight history and trend.

    Shows recent bodyweight entries, current weight, min/max/average,
    and whether you're gaining, losing, or stable.
    """
    return await bodyweight_trend(limit=limit)


@mcp.tool()
async def tool_volume_trend(weeks: int = 8) -> str:
    """Show weekly training volume trend over time.

    Tracks total volume (reps x weight) per week across all exercises.
    Shows whether overall training load is increasing, decreasing, or stable.
    Useful for periodization and recovery planning.
    """
    return await volume_trend(weeks=weeks)


def get_http_app():
    """Return the ASGI app for mounting into FastAPI (stateless HTTP transport)."""
    return mcp.streamable_http_app()


def main():
    """Run as a standalone stdio MCP server (used by Claude Desktop locally)."""
    logger.info("Starting athlete-analytics MCP server (stdio)...")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
