from fastapi import APIRouter, HTTPException

from athlete_mcp.api.dependencies import DbDep
from athlete_mcp.api.schemas.workout import (
    WorkoutCreate,
    WorkoutResponse,
    WorkoutUpdate,
    WorkoutWithSets,
)
from athlete_mcp.api.utils import build_update, now_utc, set_row_to_dict, today_iso

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


async def _get_workout_with_sets(workout_id: int, db) -> dict:
    cursor = await db.execute(
        "SELECT * FROM workouts WHERE id = ? AND deleted_at IS NULL", (workout_id,),
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
    set_dicts = [set_row_to_dict(s) for s in sets]

    exercises_performed = list(dict.fromkeys(
        s["exercise_display_name"] for s in set_dicts
    ))
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
    workout_date = workout.date or today_iso()
    cursor = await db.execute(
        """INSERT INTO workouts (date, title, bodyweight_kg, location, notes)
           VALUES (?, ?, ?, ?, ?)""",
        (workout_date, workout.title, workout.bodyweight_kg, workout.location, workout.notes),
    )
    await db.commit()

    cursor = await db.execute("SELECT * FROM workouts WHERE id = ?", (cursor.lastrowid,))
    return _row_to_response(await cursor.fetchone())


@router.get("/today", response_model=WorkoutWithSets)
async def get_today(db: DbDep):
    today = today_iso()
    cursor = await db.execute(
        "SELECT * FROM workouts WHERE date = ? AND deleted_at IS NULL", (today,),
    )
    row = await cursor.fetchone()

    if not row:
        cursor = await db.execute("INSERT INTO workouts (date) VALUES (?)", (today,))
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
        "SELECT * FROM workouts WHERE id = ? AND deleted_at IS NULL", (workout_id,),
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Workout not found")

    updates = update.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    sql, params = build_update("workouts", updates, workout_id)
    await db.execute(sql, params)
    await db.commit()

    cursor = await db.execute("SELECT * FROM workouts WHERE id = ?", (workout_id,))
    return _row_to_response(await cursor.fetchone())


@router.delete("/{workout_id}", status_code=204)
async def delete_workout(workout_id: int, db: DbDep):
    cursor = await db.execute(
        "SELECT * FROM workouts WHERE id = ? AND deleted_at IS NULL", (workout_id,),
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Workout not found")

    ts = now_utc()
    await db.execute("UPDATE workouts SET deleted_at = ? WHERE id = ?", (ts, workout_id))
    await db.execute(
        "UPDATE sets SET deleted_at = ? WHERE workout_id = ? AND deleted_at IS NULL",
        (ts, workout_id),
    )
    await db.commit()
