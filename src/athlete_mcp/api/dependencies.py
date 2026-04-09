import difflib
import re
from typing import Annotated

import aiosqlite
from fastapi import Depends, HTTPException

from athlete_mcp.database.connection import get_db

DbDep = Annotated[aiosqlite.Connection, Depends(get_db)]


async def resolve_exercise(query: str, db: aiosqlite.Connection) -> aiosqlite.Row:
    """Resolve a flexible exercise query to an exact exercise row.

    Resolution order:
    1. Exact slug match
    2. Case-insensitive display_name match
    3. Substring match
    4. Fuzzy match via difflib
    """
    normalized = re.sub(r"[\s\-]+", "_", query.strip().lower())

    # 1. Exact slug match
    cursor = await db.execute(
        "SELECT * FROM exercises WHERE name = ? AND deleted_at IS NULL", (normalized,)
    )
    row = await cursor.fetchone()
    if row:
        return row

    # 2. Case-insensitive display_name match
    cursor = await db.execute(
        "SELECT * FROM exercises WHERE LOWER(display_name) = ? AND deleted_at IS NULL",
        (query.strip().lower(),),
    )
    row = await cursor.fetchone()
    if row:
        return row

    # Load all exercises for fuzzy matching
    cursor = await db.execute(
        "SELECT * FROM exercises WHERE deleted_at IS NULL"
    )
    all_exercises = await cursor.fetchall()
    if not all_exercises:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "EXERCISE_NOT_FOUND",
                "query": query,
                "message": "No exercises in catalog. Add exercises first.",
                "suggestions": [],
            },
        )

    # 3. Substring match
    for ex in all_exercises:
        if normalized in ex["name"] or normalized in ex["display_name"].lower():
            return ex

    # 4. Fuzzy match
    all_names = [ex["name"] for ex in all_exercises]
    all_display = [ex["display_name"].lower() for ex in all_exercises]

    slug_matches = difflib.get_close_matches(normalized, all_names, n=5, cutoff=0.55)
    display_matches = difflib.get_close_matches(
        query.strip().lower(), all_display, n=5, cutoff=0.55
    )

    # If we have a strong match, return it
    if slug_matches:
        best = slug_matches[0]
        for ex in all_exercises:
            if ex["name"] == best:
                return ex

    if display_matches:
        best = display_matches[0]
        for ex in all_exercises:
            if ex["display_name"].lower() == best:
                return ex

    # No match — return suggestions
    suggestions = list(dict.fromkeys(slug_matches + display_matches))[:5]
    if not suggestions:
        # Fall back to any names for suggestions
        suggestions = [ex["display_name"] for ex in all_exercises[:5]]

    raise HTTPException(
        status_code=404,
        detail={
            "error": "EXERCISE_NOT_FOUND",
            "query": query,
            "message": f"No exercise matching '{query}'. Did you mean one of these?",
            "suggestions": suggestions,
        },
    )
