from datetime import date, datetime

from fastapi import APIRouter, HTTPException

from athlete_mcp.api.dependencies import DbDep, resolve_exercise
from athlete_mcp.api.schemas.set import SetCreate, SetResponse, SetUpdate

router = APIRouter()


def _set_to_response(row) -> dict:
    bw = row["bodyweight_kg"] or 0
    added = row["added_weight_kg"] or 0
    total_weight = bw + added if bw else added if added else None
    reps = row["reps"]
    volume = (reps * total_weight) if (reps and total_weight) else None

    return {
        "id": row["id"],
        "workout_id": row["workout_id"],
        "exercise_name": row["exercise_name"],
        "exercise_display_name": row["exercise_display_name"],
        "set_number": row["set_number"],
        "reps": reps,
        "duration_secs": row["duration_secs"],
        "distance_m": row["distance_m"],
        "bodyweight_kg": row["bodyweight_kg"],
        "added_weight_kg": added,
        "total_weight_kg": total_weight,
        "volume_kg": volume,
        "rpe": row["rpe"],
        "notes": row["notes"],
        "created_at": row["created_at"],
    }


async def _get_or_create_today(db) -> int:
    today = date.today().isoformat()
    cursor = await db.execute(
        "SELECT id FROM workouts WHERE date = ? AND deleted_at IS NULL", (today,)
    )
    row = await cursor.fetchone()
    if row:
        return row["id"]

    cursor = await db.execute("INSERT INTO workouts (date) VALUES (?)", (today,))
    await db.commit()
    return cursor.lastrowid


async def _auto_set_number(workout_id: int, exercise_name: str, db) -> int:
    cursor = await db.execute(
        """SELECT COALESCE(MAX(set_number), 0) + 1 as next_num
           FROM sets WHERE workout_id = ? AND exercise_name = ? AND deleted_at IS NULL""",
        (workout_id, exercise_name),
    )
    row = await cursor.fetchone()
    return row["next_num"]


async def update_personal_records(exercise_id: int, exercise_name: str, db) -> dict | None:
    """Recompute personal records for an exercise. Returns PR info if a new record was set."""
    # Get the exercise to know its tracking type
    cursor = await db.execute(
        "SELECT * FROM exercises WHERE id = ? AND deleted_at IS NULL", (exercise_id,)
    )
    exercise = await cursor.fetchone()
    if not exercise:
        return None

    new_prs = {}

    # PR: max reps in a single set (bodyweight only, added_weight = 0)
    cursor = await db.execute(
        """SELECT s.id, s.reps, w.date FROM sets s
           JOIN workouts w ON w.id = s.workout_id
           WHERE s.exercise_id = ? AND s.deleted_at IS NULL AND w.deleted_at IS NULL
             AND s.reps IS NOT NULL AND s.added_weight_kg = 0
           ORDER BY s.reps DESC LIMIT 1""",
        (exercise_id,),
    )
    row = await cursor.fetchone()
    if row:
        new_prs["reps"] = (row["reps"], row["id"], row["date"])

    # PR: max added weight
    cursor = await db.execute(
        """SELECT s.id, s.added_weight_kg, w.date FROM sets s
           JOIN workouts w ON w.id = s.workout_id
           WHERE s.exercise_id = ? AND s.deleted_at IS NULL AND w.deleted_at IS NULL
             AND s.added_weight_kg > 0
           ORDER BY s.added_weight_kg DESC LIMIT 1""",
        (exercise_id,),
    )
    row = await cursor.fetchone()
    if row:
        new_prs["weight"] = (row["added_weight_kg"], row["id"], row["date"])

    # PR: max single-session volume
    cursor = await db.execute(
        """SELECT s.workout_id, w.date,
                  SUM(COALESCE(s.reps, 0) * (COALESCE(s.bodyweight_kg, 0) + s.added_weight_kg)) as volume
           FROM sets s
           JOIN workouts w ON w.id = s.workout_id
           WHERE s.exercise_id = ? AND s.deleted_at IS NULL AND w.deleted_at IS NULL
             AND s.reps IS NOT NULL
           GROUP BY s.workout_id
           ORDER BY volume DESC LIMIT 1""",
        (exercise_id,),
    )
    row = await cursor.fetchone()
    if row and row["volume"]:
        new_prs["volume"] = (row["volume"], None, row["date"])

    # PR: max duration
    cursor = await db.execute(
        """SELECT s.id, s.duration_secs, w.date FROM sets s
           JOIN workouts w ON w.id = s.workout_id
           WHERE s.exercise_id = ? AND s.deleted_at IS NULL AND w.deleted_at IS NULL
             AND s.duration_secs IS NOT NULL
           ORDER BY s.duration_secs DESC LIMIT 1""",
        (exercise_id,),
    )
    row = await cursor.fetchone()
    if row:
        new_prs["duration"] = (row["duration_secs"], row["id"], row["date"])

    # PR: max distance
    cursor = await db.execute(
        """SELECT s.id, s.distance_m, w.date FROM sets s
           JOIN workouts w ON w.id = s.workout_id
           WHERE s.exercise_id = ? AND s.deleted_at IS NULL AND w.deleted_at IS NULL
             AND s.distance_m IS NOT NULL
           ORDER BY s.distance_m DESC LIMIT 1""",
        (exercise_id,),
    )
    row = await cursor.fetchone()
    if row:
        new_prs["distance"] = (row["distance_m"], row["id"], row["date"])

    # Update the personal_records table and detect new PRs
    pr_beaten = None
    for pr_type, (value, set_id, achieved_date) in new_prs.items():
        cursor = await db.execute(
            "SELECT * FROM personal_records WHERE exercise_name = ? AND pr_type = ?",
            (exercise_name, pr_type),
        )
        existing = await cursor.fetchone()

        if existing:
            old_value = existing["value"]
            if value > old_value:
                improvement = round(((value - old_value) / old_value) * 100, 1) if old_value else None
                await db.execute(
                    """UPDATE personal_records SET value = ?, set_id = ?, date_achieved = ?,
                       previous_value = ?, improvement_pct = ?, created_at = CURRENT_TIMESTAMP
                       WHERE exercise_name = ? AND pr_type = ?""",
                    (value, set_id, achieved_date, old_value, improvement, exercise_name, pr_type),
                )
                pr_beaten = {
                    "pr_type": pr_type,
                    "new_value": value,
                    "old_value": old_value,
                    "improvement_pct": improvement,
                }
            elif value < old_value:
                # PR was lost (e.g., set deleted) — update to current best
                await db.execute(
                    """UPDATE personal_records SET value = ?, set_id = ?, date_achieved = ?
                       WHERE exercise_name = ? AND pr_type = ?""",
                    (value, set_id, achieved_date, exercise_name, pr_type),
                )
        else:
            await db.execute(
                """INSERT INTO personal_records (exercise_id, exercise_name, pr_type, value, set_id, date_achieved)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (exercise_id, exercise_name, pr_type, value, set_id, achieved_date),
            )
            pr_beaten = {
                "pr_type": pr_type,
                "new_value": value,
                "old_value": None,
                "improvement_pct": None,
            }

    await db.commit()
    return pr_beaten


@router.post("", response_model=SetResponse, status_code=201)
async def log_set(set_data: SetCreate, db: DbDep):
    # Resolve exercise
    exercise = await resolve_exercise(set_data.exercise, db)

    # Get or create workout
    workout_id = set_data.workout_id
    if workout_id is None:
        workout_id = await _get_or_create_today(db)
    else:
        cursor = await db.execute(
            "SELECT id FROM workouts WHERE id = ? AND deleted_at IS NULL",
            (workout_id,),
        )
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="Workout not found")

    # Auto set number
    set_number = await _auto_set_number(workout_id, exercise["name"], db)

    # Resolve bodyweight
    bodyweight = set_data.bodyweight_kg
    if bodyweight is None:
        cursor = await db.execute(
            "SELECT bodyweight_kg FROM workouts WHERE id = ?", (workout_id,)
        )
        w = await cursor.fetchone()
        if w and w["bodyweight_kg"]:
            bodyweight = w["bodyweight_kg"]
        else:
            cursor = await db.execute(
                "SELECT weight_kg FROM bodyweight_log ORDER BY date DESC LIMIT 1"
            )
            bw_row = await cursor.fetchone()
            if bw_row:
                bodyweight = bw_row["weight_kg"]

    cursor = await db.execute(
        """INSERT INTO sets (workout_id, exercise_id, exercise_name, exercise_display_name,
           set_number, reps, duration_secs, distance_m, bodyweight_kg, added_weight_kg, rpe, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            workout_id,
            exercise["id"],
            exercise["name"],
            exercise["display_name"],
            set_number,
            set_data.reps,
            set_data.duration_secs,
            set_data.distance_m,
            bodyweight,
            set_data.added_weight_kg,
            set_data.rpe,
            set_data.notes,
        ),
    )
    await db.commit()
    new_id = cursor.lastrowid

    # Update PRs
    pr_result = await update_personal_records(exercise["id"], exercise["name"], db)

    # Fetch the set
    cursor = await db.execute("SELECT * FROM sets WHERE id = ?", (new_id,))
    row = await cursor.fetchone()
    response = _set_to_response(row)
    response["new_pr"] = pr_result
    return response


@router.get("/{set_id}", response_model=SetResponse)
async def get_set(set_id: int, db: DbDep):
    cursor = await db.execute(
        "SELECT * FROM sets WHERE id = ? AND deleted_at IS NULL", (set_id,)
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Set not found")
    return _set_to_response(row)


@router.patch("/{set_id}", response_model=SetResponse)
async def edit_set(set_id: int, update: SetUpdate, db: DbDep):
    cursor = await db.execute(
        "SELECT * FROM sets WHERE id = ? AND deleted_at IS NULL", (set_id,)
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Set not found")

    updates = update.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updates["updated_at"] = datetime.utcnow().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [set_id]

    await db.execute(f"UPDATE sets SET {set_clause} WHERE id = ?", values)
    await db.commit()

    # Re-evaluate PRs
    await update_personal_records(row["exercise_id"], row["exercise_name"], db)

    cursor = await db.execute("SELECT * FROM sets WHERE id = ?", (set_id,))
    updated_row = await cursor.fetchone()
    return _set_to_response(updated_row)


@router.delete("/{set_id}", status_code=204)
async def delete_set(set_id: int, db: DbDep):
    cursor = await db.execute(
        "SELECT * FROM sets WHERE id = ? AND deleted_at IS NULL", (set_id,)
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Set not found")

    await db.execute(
        "UPDATE sets SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?", (set_id,)
    )
    await db.commit()

    # Re-evaluate PRs after deletion
    await update_personal_records(row["exercise_id"], row["exercise_name"], db)


@router.get("/workout/{workout_id}", response_model=list[SetResponse])
async def get_sets_for_workout(workout_id: int, db: DbDep):
    cursor = await db.execute(
        """SELECT * FROM sets WHERE workout_id = ? AND deleted_at IS NULL
           ORDER BY exercise_name, set_number""",
        (workout_id,),
    )
    rows = await cursor.fetchall()
    return [_set_to_response(r) for r in rows]
