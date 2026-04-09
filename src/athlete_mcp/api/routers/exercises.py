import difflib
from datetime import datetime

from fastapi import APIRouter, HTTPException

from athlete_mcp.api.dependencies import DbDep, resolve_exercise
from athlete_mcp.api.schemas.exercise import (
    ExerciseCreate,
    ExerciseResponse,
    ExerciseSearchResult,
    ExerciseUpdate,
)

router = APIRouter()


def _row_to_response(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "display_name": row["display_name"],
        "category": row["category"],
        "muscle_groups": row["muscle_groups"],
        "equipment": row["equipment"],
        "tracking_type": row["tracking_type"],
        "is_weighted": bool(row["is_weighted"]),
        "weight_unit": row["weight_unit"],
        "description": row["description"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@router.get("", response_model=list[ExerciseResponse])
async def list_exercises(
    db: DbDep,
    category: str | None = None,
    equipment: str | None = None,
    tracking_type: str | None = None,
):
    query = "SELECT * FROM exercises WHERE deleted_at IS NULL"
    params: list = []

    if category:
        query += " AND category = ?"
        params.append(category)
    if equipment:
        query += " AND equipment = ?"
        params.append(equipment)
    if tracking_type:
        query += " AND tracking_type = ?"
        params.append(tracking_type)

    query += " ORDER BY category, name"
    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()
    return [_row_to_response(r) for r in rows]


@router.post("", response_model=ExerciseResponse, status_code=201)
async def create_exercise(exercise: ExerciseCreate, db: DbDep):
    try:
        cursor = await db.execute(
            """INSERT INTO exercises (name, display_name, category, muscle_groups, equipment,
               tracking_type, is_weighted, weight_unit, description)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                exercise.name,
                exercise.display_name,
                exercise.category,
                exercise.muscle_groups,
                exercise.equipment,
                exercise.tracking_type,
                exercise.is_weighted,
                exercise.weight_unit,
                exercise.description,
            ),
        )
        await db.commit()
        new_id = cursor.lastrowid
    except Exception as e:
        if "UNIQUE" in str(e):
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "EXERCISE_EXISTS",
                    "message": f"Exercise '{exercise.name}' already exists",
                },
            )
        raise

    cursor = await db.execute(
        "SELECT * FROM exercises WHERE id = ?", (new_id,)
    )
    row = await cursor.fetchone()
    return _row_to_response(row)


@router.get("/search/{query}", response_model=list[ExerciseSearchResult])
async def search_exercises(query: str, db: DbDep):
    cursor = await db.execute(
        "SELECT * FROM exercises WHERE deleted_at IS NULL"
    )
    all_exercises = await cursor.fetchall()

    normalized = query.strip().lower()
    results = []

    for ex in all_exercises:
        slug_score = difflib.SequenceMatcher(
            None, normalized, ex["name"]
        ).ratio()
        display_score = difflib.SequenceMatcher(
            None, normalized, ex["display_name"].lower()
        ).ratio()
        score = max(slug_score, display_score)

        # Boost substring matches
        if normalized in ex["name"] or normalized in ex["display_name"].lower():
            score = max(score, 0.85)

        if score >= 0.4:
            results.append({"exercise": _row_to_response(ex), "score": round(score, 3)})

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:10]


@router.get("/{name}", response_model=ExerciseResponse)
async def get_exercise(name: str, db: DbDep):
    row = await resolve_exercise(name, db)
    return _row_to_response(row)


@router.patch("/{name}", response_model=ExerciseResponse)
async def update_exercise(name: str, update: ExerciseUpdate, db: DbDep):
    row = await resolve_exercise(name, db)
    exercise_id = row["id"]

    updates = update.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updates["updated_at"] = datetime.utcnow().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [exercise_id]

    await db.execute(
        f"UPDATE exercises SET {set_clause} WHERE id = ?", values
    )
    await db.commit()

    cursor = await db.execute("SELECT * FROM exercises WHERE id = ?", (exercise_id,))
    row = await cursor.fetchone()
    return _row_to_response(row)


@router.delete("/{name}", status_code=204)
async def delete_exercise(name: str, db: DbDep):
    row = await resolve_exercise(name, db)
    await db.execute(
        "UPDATE exercises SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?",
        (row["id"],),
    )
    await db.commit()
