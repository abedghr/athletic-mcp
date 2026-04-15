"""MCP tool implementations for the Training Logger server.

Each function is a thin HTTP adapter — calls FastAPI, formats the response.
"""

from athlete_mcp.tools.shared import safe_api_call, format_tool_response


async def start_workout(
    title: str | None = None,
    bodyweight_kg: float | None = None,
    location: str | None = None,
    notes: str | None = None,
    date: str | None = None,
    allow_old: bool = False,
) -> str:
    """Start or retrieve a training session for a given date (defaults to today)."""
    if date:
        path = f"/workouts/by-date/{date}"
        params = {"allow_old": "true"} if allow_old else None
        result = await safe_api_call("get", path, params=params)
    else:
        result = await safe_api_call("get", "/workouts/today")
    if result["success"]:
        workout = result["data"]
        # If extra fields provided, update the workout
        updates = {}
        if title is not None:
            updates["title"] = title
        if bodyweight_kg is not None:
            updates["bodyweight_kg"] = bodyweight_kg
        if location is not None:
            updates["location"] = location
        if notes is not None:
            updates["notes"] = notes

        if updates:
            update_result = await safe_api_call(
                "patch", f"/workouts/{workout['id']}", json=updates
            )
            if update_result["success"]:
                workout.update(update_result["data"])

        sets_info = f" with {workout.get('total_sets', 0)} sets logged" if workout.get("total_sets") else ""
        return format_tool_response({
            "success": True,
            "data": workout,
            "message": f"Workout session ready for {workout['date']}{sets_info}.",
        })
    return format_tool_response(result)


async def log_set(
    exercise: str,
    reps: int | None = None,
    duration_secs: int | None = None,
    distance_m: float | None = None,
    added_weight_kg: float = 0,
    bodyweight_kg: float | None = None,
    rpe: float | None = None,
    notes: str | None = None,
    date: str | None = None,
    allow_old: bool = False,
) -> str:
    """Log a single training set for any exercise.

    Attaches to the workout session for *date* (defaults to today, creating the
    session on first set). Use *date* (YYYY-MM-DD) to backlog past workouts.
    """
    payload: dict = {"exercise": exercise, "added_weight_kg": added_weight_kg}
    if reps is not None:
        payload["reps"] = reps
    if duration_secs is not None:
        payload["duration_secs"] = duration_secs
    if distance_m is not None:
        payload["distance_m"] = distance_m
    if bodyweight_kg is not None:
        payload["bodyweight_kg"] = bodyweight_kg
    if rpe is not None:
        payload["rpe"] = rpe
    if notes is not None:
        payload["notes"] = notes
    if date is not None:
        payload["date"] = date
    if allow_old:
        payload["allow_old"] = True

    result = await safe_api_call("post", "/sets", json=payload)
    if not result["success"]:
        return format_tool_response(result)

    data = result["data"]
    # Build informative message
    metric_parts = []
    if data.get("reps"):
        metric_parts.append(f"{data['reps']} reps")
    if data.get("duration_secs"):
        metric_parts.append(f"{data['duration_secs']}s")
    if data.get("distance_m"):
        metric_parts.append(f"{data['distance_m']}m")
    if data.get("added_weight_kg", 0) > 0:
        metric_parts.append(f"+{data['added_weight_kg']}kg")

    metrics = ", ".join(metric_parts)
    msg = f"Set {data['set_number']} of {data['exercise_display_name']}: {metrics}."

    if data.get("new_pr"):
        pr = data["new_pr"]
        pr_msg = f" NEW PR! {pr['pr_type']}: {pr['new_value']}"
        if pr.get("old_value"):
            pr_msg += f" (was {pr['old_value']}, +{pr.get('improvement_pct', '?')}%)"
        msg += pr_msg

    return format_tool_response({"success": True, "data": data, "message": msg})


async def log_bodyweight(
    weight_kg: float,
    time_of_day: str = "morning",
    notes: str | None = None,
    date: str | None = None,
    allow_old: bool = False,
) -> str:
    """Log a bodyweight measurement.

    Defaults to today. Pass *date* (YYYY-MM-DD) to backlog a prior measurement.
    time_of_day can be 'morning', 'evening', or 'post_workout'.
    """
    params: dict = {"weight_kg": weight_kg, "time_of_day": time_of_day}
    if notes:
        params["notes"] = notes
    if date:
        params["date"] = date
    if allow_old:
        params["allow_old"] = "true"
    result = await safe_api_call("post", "/analytics/bodyweight", params=params)
    if result["success"]:
        log_date = result["data"].get("date", "today")
        return format_tool_response({
            "success": True,
            "data": result["data"],
            "message": f"Bodyweight logged: {weight_kg}kg ({time_of_day}) on {log_date}.",
        })
    return format_tool_response(result)


async def get_today(date: str | None = None, allow_old: bool = False) -> str:
    """Get a full summary of a training session.

    Defaults to today. Pass *date* (YYYY-MM-DD) to see a backdated session.
    Creates the session if it doesn't exist yet.
    """
    if date:
        params = {"allow_old": "true"} if allow_old else None
        result = await safe_api_call("get", f"/workouts/by-date/{date}", params=params)
    else:
        result = await safe_api_call("get", "/workouts/today")
    if not result["success"]:
        return format_tool_response(result)

    data = result["data"]
    total = data.get("total_sets", 0)
    exercises = data.get("exercises_performed", [])

    if total == 0:
        msg = f"Session for {data['date']}: No sets logged yet."
    else:
        ex_list = ", ".join(exercises)
        vol = data.get("total_volume_kg")
        vol_str = f", total volume: {vol}kg" if vol else ""
        msg = f"Session for {data['date']}: {total} sets across {len(exercises)} exercises ({ex_list}){vol_str}."

    return format_tool_response({"success": True, "data": data, "message": msg})


async def add_exercise(
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

    The exercise catalog is fully dynamic — add any exercise for any sport or training modality.
    name: slug format like 'pull_up', 'bench_press'
    display_name: human-readable like 'Pull Up', 'Bench Press'
    category: push|pull|core|legs|full_body|isometric|cardio|sport_specific
    tracking_type: reps|duration|distance|rounds
    """
    payload = {
        "name": name,
        "display_name": display_name,
        "category": category,
        "tracking_type": tracking_type,
        "is_weighted": is_weighted,
    }
    if equipment:
        payload["equipment"] = equipment
    if muscle_groups:
        payload["muscle_groups"] = muscle_groups
    if description:
        payload["description"] = description

    result = await safe_api_call("post", "/exercises", json=payload)
    if result["success"]:
        return format_tool_response({
            "success": True,
            "data": result["data"],
            "message": f"Exercise '{display_name}' added to catalog (category: {category}, tracking: {tracking_type}).",
        })
    return format_tool_response(result)


async def list_exercises(
    category: str | None = None,
    equipment: str | None = None,
) -> str:
    """List all available exercises in the catalog.

    Optionally filter by category (push, pull, core, legs, etc.) or equipment type.
    Shows exercise names, categories, and tracking types.
    """
    params = {}
    if category:
        params["category"] = category
    if equipment:
        params["equipment"] = equipment

    result = await safe_api_call("get", "/exercises", params=params)
    if not result["success"]:
        return format_tool_response(result)

    data = result["data"]
    count = len(data)
    filter_str = ""
    if category:
        filter_str += f" in category '{category}'"
    if equipment:
        filter_str += f" with equipment '{equipment}'"

    return format_tool_response({
        "success": True,
        "data": data,
        "message": f"Found {count} exercises{filter_str}.",
    })


async def edit_set(
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

    Update any field of an existing set by its ID. Only provide the fields you want to change.
    Personal records are automatically re-evaluated after the edit.
    """
    payload = {}
    if reps is not None:
        payload["reps"] = reps
    if duration_secs is not None:
        payload["duration_secs"] = duration_secs
    if distance_m is not None:
        payload["distance_m"] = distance_m
    if added_weight_kg is not None:
        payload["added_weight_kg"] = added_weight_kg
    if bodyweight_kg is not None:
        payload["bodyweight_kg"] = bodyweight_kg
    if rpe is not None:
        payload["rpe"] = rpe
    if notes is not None:
        payload["notes"] = notes

    result = await safe_api_call("patch", f"/sets/{set_id}", json=payload)
    if result["success"]:
        data = result["data"]
        return format_tool_response({
            "success": True,
            "data": data,
            "message": f"Set {set_id} updated ({data['exercise_display_name']}, set #{data['set_number']}).",
        })
    return format_tool_response(result)


async def delete_set(set_id: int) -> str:
    """Remove a set from today's session (soft delete).

    The set is marked as deleted but not permanently removed.
    Personal records are automatically re-evaluated after deletion.
    """
    result = await safe_api_call("delete", f"/sets/{set_id}")
    if result["success"]:
        return format_tool_response({
            "success": True,
            "message": f"Set {set_id} deleted.",
        })
    return format_tool_response(result)


async def rate_workout(
    rating: int,
    notes: str | None = None,
    duration_mins: int | None = None,
    date: str | None = None,
    allow_old: bool = False,
) -> str:
    """Rate a training session on a 1-5 scale (defaults to today)."""
    if date:
        params = {"allow_old": "true"} if allow_old else None
        session_result = await safe_api_call("get", f"/workouts/by-date/{date}", params=params)
    else:
        session_result = await safe_api_call("get", "/workouts/today")
    if not session_result["success"]:
        return format_tool_response(session_result)

    workout_id = session_result["data"]["id"]
    payload: dict = {"rating": rating}
    if notes:
        payload["notes"] = notes
    if duration_mins:
        payload["duration_mins"] = duration_mins

    result = await safe_api_call("patch", f"/workouts/{workout_id}", json=payload)
    if result["success"]:
        labels = {1: "terrible", 2: "poor", 3: "average", 4: "good", 5: "excellent"}
        label = labels.get(rating, str(rating))
        session_date = result["data"].get("date", "today")
        return format_tool_response({
            "success": True,
            "data": result["data"],
            "message": f"Session on {session_date} rated {rating}/5 ({label}).",
        })
    return format_tool_response(result)


async def search_exercise(query: str) -> str:
    """Search for an exercise by name.

    Uses fuzzy matching to find exercises. Useful when you're not sure of the exact name.
    Returns ranked matches with similarity scores.
    """
    result = await safe_api_call("get", f"/exercises/search/{query}")
    if not result["success"]:
        return format_tool_response(result)

    data = result["data"]
    if not data:
        return format_tool_response({
            "success": True,
            "data": [],
            "message": f"No exercises matching '{query}'.",
        })

    top = data[0]["exercise"]["display_name"]
    return format_tool_response({
        "success": True,
        "data": data,
        "message": f"Found {len(data)} matches for '{query}'. Best match: {top}.",
    })
