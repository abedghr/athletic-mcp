"""MCP tool implementations for the Performance Analytics server.

Each function is a thin HTTP adapter — calls FastAPI, formats the response.
"""

from athlete_mcp.tools.shared import safe_api_call, format_tool_response


async def get_prs(exercise: str | None = None) -> str:
    """Get personal records — all exercises or a specific one.

    Shows your best performances: max reps, max weight, max volume, max duration.
    Includes when the PR was set and how long ago.
    """
    if exercise:
        result = await safe_api_call("get", f"/analytics/prs/{exercise}")
    else:
        result = await safe_api_call("get", "/analytics/prs")

    if not result["success"]:
        return format_tool_response(result)

    data = result["data"]
    if not data:
        scope = f"for {exercise}" if exercise else ""
        return format_tool_response({
            "success": True,
            "data": [],
            "message": f"No personal records found {scope}. Start logging sets to track PRs!",
        })

    count = len(data)
    exercises = len(set(pr["exercise_name"] for pr in data))
    return format_tool_response({
        "success": True,
        "data": data,
        "message": f"{count} personal records across {exercises} exercise(s).",
    })


async def weekly_summary(week_offset: int = 0) -> str:
    """Get a training summary for the current or a past week.

    Shows sessions, sets, volume, exercises, and RPE.
    Includes comparison deltas vs the previous week.
    week_offset: 0 = this week, -1 = last week, -2 = two weeks ago, etc.
    """
    result = await safe_api_call(
        "get", "/analytics/weekly-summary", params={"week_offset": week_offset}
    )
    if not result["success"]:
        return format_tool_response(result)

    data = result["data"]
    stats = data["current_week"]
    week_label = "This week" if week_offset == 0 else f"Week of {data['week_start']}"

    msg = (
        f"{week_label}: {stats['total_sessions']} sessions, "
        f"{stats['total_sets']} sets, {stats['total_reps']} reps, "
        f"{stats['total_volume_kg']}kg volume, "
        f"{stats['unique_exercises']} exercises."
    )

    deltas = data.get("deltas")
    if deltas:
        parts = []
        if deltas["sets"] != 0:
            parts.append(f"sets {'+' if deltas['sets'] > 0 else ''}{deltas['sets']}")
        if deltas["volume_kg"] != 0:
            parts.append(f"volume {'+' if deltas['volume_kg'] > 0 else ''}{deltas['volume_kg']}kg")
        if parts:
            msg += f" vs last week: {', '.join(parts)}."

    return format_tool_response({"success": True, "data": data, "message": msg})


async def exercise_history(exercise: str, limit: int = 20) -> str:
    """Get session-by-session history for a specific exercise.

    Shows every training session where you performed this exercise,
    with sets, reps, weights, volume, and RPE for each session.
    """
    result = await safe_api_call(
        "get",
        f"/analytics/exercise/{exercise}/history",
        params={"limit": limit},
    )
    if not result["success"]:
        return format_tool_response(result)

    data = result["data"]
    count = data.get("total_sessions", 0)
    name = data.get("exercise_display_name", exercise)

    if count == 0:
        return format_tool_response({
            "success": True,
            "data": data,
            "message": f"No history found for {name}.",
        })

    return format_tool_response({
        "success": True,
        "data": data,
        "message": f"{name}: {count} sessions found.",
    })


async def exercise_stats(exercise: str, period_days: int = 30) -> str:
    """Get aggregate stats for an exercise over a time period.

    Shows total sessions, sets, reps, volume, max weight, averages, and trend direction.
    period_days: number of days to look back (default 30).
    """
    result = await safe_api_call(
        "get",
        f"/analytics/exercise/{exercise}/stats",
        params={"period_days": period_days},
    )
    if not result["success"]:
        return format_tool_response(result)

    data = result["data"]
    name = data.get("exercise_display_name", exercise)

    if data.get("total_sets", 0) == 0:
        return format_tool_response({
            "success": True,
            "data": data,
            "message": f"No data for {name} in the last {period_days} days.",
        })

    trend_str = f", trend: {data['trend']}" if data.get("trend") else ""
    return format_tool_response({
        "success": True,
        "data": data,
        "message": (
            f"{name} ({period_days}d): {data['total_sessions']} sessions, "
            f"{data['total_sets']} sets, {data['total_reps']} reps, "
            f"{data['total_volume_kg']}kg volume{trend_str}."
        ),
    })


async def detect_plateau(window_weeks: int = 4, threshold_pct: float = 5.0) -> str:
    """Find exercises where progress has stalled.

    Analyzes your training data over the specified window to detect plateaus.
    Compares the first half of the window to the second half.
    Returns plateaued exercises with suggested actions, plus improving and insufficient-data lists.
    """
    result = await safe_api_call(
        "get",
        "/analytics/plateaus",
        params={"window_weeks": window_weeks, "threshold_pct": threshold_pct},
    )
    if not result["success"]:
        return format_tool_response(result)

    data = result["data"]
    p_count = len(data.get("plateaued", []))
    i_count = len(data.get("improving", []))

    if p_count == 0 and i_count == 0:
        return format_tool_response({
            "success": True,
            "data": data,
            "message": "Not enough data to detect plateaus. Keep training!",
        })

    msg = f"Analysis over {window_weeks} weeks: {p_count} plateaued, {i_count} improving."
    if p_count > 0:
        names = [e["exercise_display_name"] for e in data["plateaued"]]
        msg += f" Plateaued: {', '.join(names)}."

    return format_tool_response({"success": True, "data": data, "message": msg})


async def training_frequency(period_days: int = 30) -> str:
    """Show how often each exercise and category is trained.

    Displays session counts, total sets, last performed date, and days since last session.
    Also shows frequency breakdown by category (push, pull, legs, etc.).
    """
    result = await safe_api_call(
        "get", "/analytics/frequency", params={"period_days": period_days}
    )
    if not result["success"]:
        return format_tool_response(result)

    data = result["data"]
    ex_count = len(data.get("exercises", []))
    cats = data.get("by_category", {})
    cat_str = ", ".join(f"{k}: {v}" for k, v in sorted(cats.items(), key=lambda x: -x[1]))

    return format_tool_response({
        "success": True,
        "data": data,
        "message": f"Training frequency ({period_days}d): {ex_count} exercises. By category: {cat_str}.",
    })


async def bodyweight_trend(limit: int = 30) -> str:
    """Get your bodyweight history and trend.

    Shows recent bodyweight entries and whether you're gaining, losing, or stable.
    """
    result = await safe_api_call(
        "get", "/analytics/bodyweight", params={"limit": limit}
    )
    if not result["success"]:
        return format_tool_response(result)

    data = result["data"]
    if not data.get("entries"):
        return format_tool_response({
            "success": True,
            "data": data,
            "message": "No bodyweight data logged yet. Use log_bodyweight to start tracking.",
        })

    current = data.get("current_weight_kg")
    trend = data.get("trend", "unknown")
    count = len(data["entries"])

    return format_tool_response({
        "success": True,
        "data": data,
        "message": f"Bodyweight: {current}kg (current), trend: {trend}, {count} entries.",
    })


async def volume_trend(weeks: int = 8) -> str:
    """Show weekly training volume over time.

    Tracks total volume (reps x weight) per week to see if overall training load
    is increasing, decreasing, or stable.
    """
    result = await safe_api_call(
        "get", "/analytics/volume-trend", params={"weeks": weeks}
    )
    if not result["success"]:
        return format_tool_response(result)

    data = result["data"]
    week_data = data.get("data", [])
    if not week_data:
        return format_tool_response({
            "success": True,
            "data": data,
            "message": f"No training data in the last {weeks} weeks.",
        })

    trend = data.get("trend", "unknown")
    total = sum(w["total_volume_kg"] for w in week_data)
    return format_tool_response({
        "success": True,
        "data": data,
        "message": f"Volume trend ({weeks} weeks): {len(week_data)} active weeks, {round(total, 2)}kg total, trend: {trend}.",
    })
