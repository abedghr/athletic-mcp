"""Shared utilities for routers.

Single source of truth for:
- Weight and volume calculations
- Timestamp generation
- Safe dynamic UPDATE builder
- Set row → response dict conversion
"""

from datetime import date, datetime, timedelta
from typing import Any


# ---------------------------------------------------------------------------
# Timestamps — use one strategy everywhere: Python-generated UTC ISO strings.
# ---------------------------------------------------------------------------

def now_utc() -> str:
    """Current UTC timestamp as ISO-8601 string (no timezone suffix)."""
    return datetime.utcnow().isoformat()


def today_iso() -> str:
    """Today's date as YYYY-MM-DD."""
    return date.today().isoformat()


def get_monday(d: date) -> date:
    """Monday of the week containing *d*."""
    return d - timedelta(days=d.weekday())


# ---------------------------------------------------------------------------
# Weight / volume — one function, used everywhere.
# ---------------------------------------------------------------------------

def compute_weight_and_volume(
    bodyweight_kg: float | None,
    added_weight_kg: float | None,
    reps: int | None,
) -> tuple[float | None, float | None]:
    """Compute total_weight_kg and volume_kg from a set's fields.

    Returns (total_weight_kg, volume_kg). Either or both may be None.
    """
    bw = bodyweight_kg or 0.0
    added = added_weight_kg or 0.0
    total = bw + added if bw else (added if added else None)
    volume = (reps * total) if (reps and total) else None
    return total, volume


# ---------------------------------------------------------------------------
# Set row → dict — one converter, used by sets and workouts routers.
# ---------------------------------------------------------------------------

def set_row_to_dict(row) -> dict:
    """Convert a DB set row to an API-ready dict with computed fields."""
    total_weight, volume = compute_weight_and_volume(
        row["bodyweight_kg"], row["added_weight_kg"], row["reps"],
    )
    return {
        "id": row["id"],
        "workout_id": row["workout_id"],
        "exercise_name": row["exercise_name"],
        "exercise_display_name": row["exercise_display_name"],
        "set_number": row["set_number"],
        "reps": row["reps"],
        "duration_secs": row["duration_secs"],
        "distance_m": row["distance_m"],
        "bodyweight_kg": row["bodyweight_kg"],
        "added_weight_kg": row["added_weight_kg"] or 0.0,
        "total_weight_kg": total_weight,
        "volume_kg": volume,
        "rpe": row["rpe"],
        "notes": row["notes"],
        "created_at": row["created_at"],
    }


# ---------------------------------------------------------------------------
# Safe dynamic UPDATE — builds SET clause from Pydantic model_dump output.
# Column names come from Pydantic schema attributes (not user input), so
# this is safe from SQL injection.  We validate the set of allowed columns
# explicitly anyway to make auditing easy.
# ---------------------------------------------------------------------------

_EXERCISE_COLUMNS = frozenset({
    "display_name", "category", "muscle_groups", "equipment",
    "tracking_type", "is_weighted", "weight_unit", "description",
})

_WORKOUT_COLUMNS = frozenset({
    "title", "bodyweight_kg", "location", "notes", "rating", "duration_mins",
})

_SET_COLUMNS = frozenset({
    "reps", "duration_secs", "distance_m", "bodyweight_kg",
    "added_weight_kg", "rpe", "notes",
})

_ALLOWED_COLUMNS: dict[str, frozenset[str]] = {
    "exercises": _EXERCISE_COLUMNS,
    "workouts": _WORKOUT_COLUMNS,
    "sets": _SET_COLUMNS,
}


def build_update(
    table: str,
    updates: dict[str, Any],
    row_id: int,
) -> tuple[str, list[Any]]:
    """Build a parameterized UPDATE statement.

    Returns (sql, params).  Raises ValueError if *updates* contains a column
    not in the allow-list for *table*.

    Automatically appends ``updated_at = ?`` with the current timestamp.
    """
    allowed = _ALLOWED_COLUMNS.get(table)
    if allowed is None:
        raise ValueError(f"Unknown table: {table}")

    bad = set(updates) - allowed
    if bad:
        raise ValueError(f"Columns not allowed for {table}: {bad}")

    updates["updated_at"] = now_utc()
    set_clause = ", ".join(f"{col} = ?" for col in updates)
    params = list(updates.values()) + [row_id]
    return f"UPDATE {table} SET {set_clause} WHERE id = ?", params


# ---------------------------------------------------------------------------
# Average helper — avoids the scattered `if values: sum/len else None` pattern.
# ---------------------------------------------------------------------------

def safe_avg(values: list[float | int]) -> float | None:
    """Average of *values*, or None if empty."""
    return round(sum(values) / len(values), 1) if values else None
