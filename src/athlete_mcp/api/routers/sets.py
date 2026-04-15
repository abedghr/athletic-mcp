import logging

from fastapi import APIRouter, HTTPException

from athlete_mcp.api.dependencies import DbDep, resolve_exercise
from athlete_mcp.api.routers.workouts import get_or_create_workout_for_date
from athlete_mcp.api.schemas.set import PRInfo, SetCreate, SetResponse, SetUpdate
from athlete_mcp.api.utils import (
    build_update,
    now_utc,
    set_row_to_dict,
    validate_entry_date,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _auto_set_number(workout_id: int, exercise_name: str, db) -> int:
    cursor = await db.execute(
        """SELECT COALESCE(MAX(set_number), 0) + 1 as next_num
           FROM sets WHERE workout_id = ? AND exercise_name = ? AND deleted_at IS NULL""",
        (workout_id, exercise_name),
    )
    return (await cursor.fetchone())["next_num"]


async def _resolve_bodyweight(workout_id: int, explicit: float | None, db) -> float | None:
    """Resolve bodyweight: explicit value > workout bodyweight > last bodyweight_log."""
    if explicit is not None:
        return explicit

    cursor = await db.execute(
        "SELECT bodyweight_kg FROM workouts WHERE id = ?", (workout_id,),
    )
    row = await cursor.fetchone()
    if row and row["bodyweight_kg"]:
        return row["bodyweight_kg"]

    cursor = await db.execute(
        "SELECT weight_kg FROM bodyweight_log ORDER BY date DESC LIMIT 1",
    )
    row = await cursor.fetchone()
    return row["weight_kg"] if row else None


# ---------------------------------------------------------------------------
# Personal records — recompute after every set insert/update/delete.
# ---------------------------------------------------------------------------

_PR_QUERIES = {
    "reps": """
        SELECT s.id, s.reps as value, w.date FROM sets s
        JOIN workouts w ON w.id = s.workout_id
        WHERE s.exercise_id = ? AND s.deleted_at IS NULL AND w.deleted_at IS NULL
          AND s.reps IS NOT NULL AND s.added_weight_kg = 0
        ORDER BY s.reps DESC LIMIT 1
    """,
    "weight": """
        SELECT s.id, s.added_weight_kg as value, w.date FROM sets s
        JOIN workouts w ON w.id = s.workout_id
        WHERE s.exercise_id = ? AND s.deleted_at IS NULL AND w.deleted_at IS NULL
          AND s.added_weight_kg > 0
        ORDER BY s.added_weight_kg DESC LIMIT 1
    """,
    "volume": """
        SELECT NULL as id,
               SUM(COALESCE(s.reps, 0) * (COALESCE(s.bodyweight_kg, 0) + s.added_weight_kg)) as value,
               w.date
        FROM sets s
        JOIN workouts w ON w.id = s.workout_id
        WHERE s.exercise_id = ? AND s.deleted_at IS NULL AND w.deleted_at IS NULL
          AND s.reps IS NOT NULL
        GROUP BY s.workout_id ORDER BY value DESC LIMIT 1
    """,
    "duration": """
        SELECT s.id, s.duration_secs as value, w.date FROM sets s
        JOIN workouts w ON w.id = s.workout_id
        WHERE s.exercise_id = ? AND s.deleted_at IS NULL AND w.deleted_at IS NULL
          AND s.duration_secs IS NOT NULL
        ORDER BY s.duration_secs DESC LIMIT 1
    """,
    "distance": """
        SELECT s.id, s.distance_m as value, w.date FROM sets s
        JOIN workouts w ON w.id = s.workout_id
        WHERE s.exercise_id = ? AND s.deleted_at IS NULL AND w.deleted_at IS NULL
          AND s.distance_m IS NOT NULL
        ORDER BY s.distance_m DESC LIMIT 1
    """,
}


async def update_personal_records(
    exercise_id: int, exercise_name: str, db,
) -> PRInfo | None:
    """Recompute all PR types for an exercise. Returns info if a new PR was set."""
    pr_beaten: PRInfo | None = None

    for pr_type, sql in _PR_QUERIES.items():
        cursor = await db.execute(sql, (exercise_id,))
        best = await cursor.fetchone()
        if not best or not best["value"]:
            continue

        value = best["value"]
        set_id = best["id"]
        achieved_date = best["date"]

        # Look up existing record.
        cursor = await db.execute(
            "SELECT * FROM personal_records WHERE exercise_name = ? AND pr_type = ?",
            (exercise_name, pr_type),
        )
        existing = await cursor.fetchone()

        if not existing:
            # First record for this PR type.
            await db.execute(
                """INSERT INTO personal_records
                   (exercise_id, exercise_name, pr_type, value, set_id, date_achieved)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (exercise_id, exercise_name, pr_type, value, set_id, achieved_date),
            )
            pr_beaten = PRInfo(
                pr_type=pr_type, new_value=value, old_value=None, improvement_pct=None,
            )
        elif value > existing["value"]:
            # New PR — record the old value for messaging.
            old_value = existing["value"]
            improvement = (
                round(((value - old_value) / old_value) * 100, 1)
                if old_value else None
            )
            await db.execute(
                """UPDATE personal_records
                   SET value = ?, set_id = ?, date_achieved = ?,
                       previous_value = ?, improvement_pct = ?
                   WHERE exercise_name = ? AND pr_type = ?""",
                (value, set_id, achieved_date, old_value, improvement,
                 exercise_name, pr_type),
            )
            pr_beaten = PRInfo(
                pr_type=pr_type, new_value=value,
                old_value=old_value, improvement_pct=improvement,
            )
        elif value < existing["value"]:
            # PR was lost (deleted set) — update to current best without claiming new PR.
            await db.execute(
                """UPDATE personal_records
                   SET value = ?, set_id = ?, date_achieved = ?
                   WHERE exercise_name = ? AND pr_type = ?""",
                (value, set_id, achieved_date, exercise_name, pr_type),
            )

    await db.commit()
    return pr_beaten


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=SetResponse, status_code=201)
async def log_set(set_data: SetCreate, db: DbDep):
    exercise = await resolve_exercise(set_data.exercise, db)

    workout_id = set_data.workout_id
    if workout_id is None:
        workout_date = validate_entry_date(set_data.date, allow_old=set_data.allow_old)
        workout_id = await get_or_create_workout_for_date(db, workout_date)
    else:
        cursor = await db.execute(
            "SELECT id FROM workouts WHERE id = ? AND deleted_at IS NULL", (workout_id,),
        )
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="Workout not found")

    set_number = await _auto_set_number(workout_id, exercise["name"], db)
    bodyweight = await _resolve_bodyweight(workout_id, set_data.bodyweight_kg, db)

    cursor = await db.execute(
        """INSERT INTO sets (workout_id, exercise_id, exercise_name, exercise_display_name,
           set_number, reps, duration_secs, distance_m, bodyweight_kg, added_weight_kg, rpe, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            workout_id, exercise["id"], exercise["name"], exercise["display_name"],
            set_number, set_data.reps, set_data.duration_secs, set_data.distance_m,
            bodyweight, set_data.added_weight_kg, set_data.rpe, set_data.notes,
        ),
    )
    await db.commit()
    new_id = cursor.lastrowid

    pr_result = await update_personal_records(exercise["id"], exercise["name"], db)

    cursor = await db.execute("SELECT * FROM sets WHERE id = ?", (new_id,))
    response = set_row_to_dict(await cursor.fetchone())
    response["new_pr"] = pr_result.model_dump() if pr_result else None
    return response


@router.get("/{set_id}", response_model=SetResponse)
async def get_set(set_id: int, db: DbDep):
    cursor = await db.execute(
        "SELECT * FROM sets WHERE id = ? AND deleted_at IS NULL", (set_id,),
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Set not found")
    return set_row_to_dict(row)


@router.patch("/{set_id}", response_model=SetResponse)
async def edit_set(set_id: int, update: SetUpdate, db: DbDep):
    cursor = await db.execute(
        "SELECT * FROM sets WHERE id = ? AND deleted_at IS NULL", (set_id,),
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Set not found")

    updates = update.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    sql, params = build_update("sets", updates, set_id)
    await db.execute(sql, params)
    await db.commit()

    await update_personal_records(row["exercise_id"], row["exercise_name"], db)

    cursor = await db.execute("SELECT * FROM sets WHERE id = ?", (set_id,))
    return set_row_to_dict(await cursor.fetchone())


@router.delete("/{set_id}", status_code=204)
async def delete_set(set_id: int, db: DbDep):
    cursor = await db.execute(
        "SELECT * FROM sets WHERE id = ? AND deleted_at IS NULL", (set_id,),
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Set not found")

    await db.execute("UPDATE sets SET deleted_at = ? WHERE id = ?", (now_utc(), set_id))
    await db.commit()

    await update_personal_records(row["exercise_id"], row["exercise_name"], db)


@router.get("/workout/{workout_id}", response_model=list[SetResponse])
async def get_sets_for_workout(workout_id: int, db: DbDep):
    cursor = await db.execute(
        """SELECT * FROM sets WHERE workout_id = ? AND deleted_at IS NULL
           ORDER BY exercise_name, set_number""",
        (workout_id,),
    )
    return [set_row_to_dict(r) for r in await cursor.fetchall()]
