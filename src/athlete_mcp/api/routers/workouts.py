from datetime import date, datetime

from fastapi import APIRouter, HTTPException

from athlete_mcp.api.dependencies import DbDep
from athlete_mcp.api.schemas.workout import (
    WorkoutCreate,
    WorkoutResponse,
    WorkoutUpdate,
    WorkoutWithSets,
)

router = APIRouter()


def _row_to_response(row) -> dict:
    return {
        "id": row["id"],
        "date": row["date"],
        "title": row["title"],
        "bodyweight_kg": row["bodyweight_kg"],
        "location": row["location"],
        "notes": row["notes"],
        "rating": row["rating"],
        "duration_mins": row["duration_mins"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _set_to_dict(row) -> dict:
    bw = row["bodyweight_kg"] or 0
    added = row["added_weight_kg"] or 0
    total_weight = bw + added if bw else added if added else None
    reps = row["reps"]
    volume = (reps * total_weight) if (reps and total_weight) else None

    return {
        "id": row["id"],
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


async def _get_workout_with_sets(workout_id: int, db) -> dict:
    cursor = await db.execute(
        "SELECT * FROM workouts WHERE id = ? AND deleted_at IS NULL",
        (workout_id,),
    )
    workout = await cursor.fetchone()
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")

    cursor = await db.execute(
        """SELECT * FROM sets WHERE workout_id = ? AND deleted_at IS NULL
           ORDER BY exercise_name, set_number""",
        (workout_id,),
    )
    sets = await cursor.fetchall()
    set_dicts = [_set_to_dict(s) for s in sets]

    exercises_performed = list(dict.fromkeys(s["exercise_display_name"] for s in set_dicts))
    total_volume = sum(s["volume_kg"] for s in set_dicts if s["volume_kg"])

    result = _row_to_response(workout)
    result["sets"] = set_dicts
    result["total_sets"] = len(set_dicts)
    result["total_volume_kg"] = round(total_volume, 2) if total_volume else None
    result["exercises_performed"] = exercises_performed
    return result


@router.get("", response_model=list[WorkoutResponse])
async def list_workouts(
    db: DbDep,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 20,
):
    query = "SELECT * FROM workouts WHERE deleted_at IS NULL"
    params: list = []

    if date_from:
        query += " AND date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND date <= ?"
        params.append(date_to)

    query += " ORDER BY date DESC LIMIT ?"
    params.append(limit)

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()
    return [_row_to_response(r) for r in rows]


@router.post("", response_model=WorkoutResponse, status_code=201)
async def create_workout(workout: WorkoutCreate, db: DbDep):
    workout_date = workout.date or date.today().isoformat()
    cursor = await db.execute(
        """INSERT INTO workouts (date, title, bodyweight_kg, location, notes)
           VALUES (?, ?, ?, ?, ?)""",
        (workout_date, workout.title, workout.bodyweight_kg, workout.location, workout.notes),
    )
    await db.commit()

    cursor = await db.execute(
        "SELECT * FROM workouts WHERE id = ?", (cursor.lastrowid,)
    )
    row = await cursor.fetchone()
    return _row_to_response(row)


@router.get("/today", response_model=WorkoutWithSets)
async def get_today(db: DbDep):
    today = date.today().isoformat()
    cursor = await db.execute(
        "SELECT * FROM workouts WHERE date = ? AND deleted_at IS NULL", (today,)
    )
    row = await cursor.fetchone()

    if not row:
        cursor = await db.execute(
            "INSERT INTO workouts (date) VALUES (?)", (today,)
        )
        await db.commit()
        workout_id = cursor.lastrowid
    else:
        workout_id = row["id"]

    return await _get_workout_with_sets(workout_id, db)


@router.get("/{workout_id}", response_model=WorkoutWithSets)
async def get_workout(workout_id: int, db: DbDep):
    return await _get_workout_with_sets(workout_id, db)


@router.patch("/{workout_id}", response_model=WorkoutResponse)
async def update_workout(workout_id: int, update: WorkoutUpdate, db: DbDep):
    cursor = await db.execute(
        "SELECT * FROM workouts WHERE id = ? AND deleted_at IS NULL",
        (workout_id,),
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Workout not found")

    updates = update.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updates["updated_at"] = datetime.utcnow().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [workout_id]

    await db.execute(f"UPDATE workouts SET {set_clause} WHERE id = ?", values)
    await db.commit()

    cursor = await db.execute("SELECT * FROM workouts WHERE id = ?", (workout_id,))
    row = await cursor.fetchone()
    return _row_to_response(row)


@router.delete("/{workout_id}", status_code=204)
async def delete_workout(workout_id: int, db: DbDep):
    cursor = await db.execute(
        "SELECT * FROM workouts WHERE id = ? AND deleted_at IS NULL",
        (workout_id,),
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Workout not found")

    now = datetime.utcnow().isoformat()
    await db.execute(
        "UPDATE workouts SET deleted_at = ? WHERE id = ?", (now, workout_id)
    )
    await db.execute(
        "UPDATE sets SET deleted_at = ? WHERE workout_id = ? AND deleted_at IS NULL",
        (now, workout_id),
    )
    await db.commit()
