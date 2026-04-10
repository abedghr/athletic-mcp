"""FastAPI dependencies shared across routers.

Defines:
- DbDep — the annotated database dependency for endpoint signatures
- resolve_exercise() — single, unified exercise name resolver
"""

import logging
import re
from difflib import SequenceMatcher
from typing import Annotated, Any

from fastapi import Depends, HTTPException

from athlete_mcp.database.connection import Database, get_db

logger = logging.getLogger(__name__)

DbDep = Annotated[Database, Depends(get_db)]

# Minimum similarity score to accept a fuzzy match automatically.
_AUTO_MATCH_CUTOFF = 0.6
# Minimum score to include in suggestions list.
_SUGGESTION_CUTOFF = 0.4


def _normalize(name: str) -> str:
    """Normalize an exercise query for matching: lowercase, underscores."""
    return re.sub(r"[\s\-]+", "_", name.strip().lower())


def _score(query: str, candidate_slug: str, candidate_display: str) -> float:
    """Score how well *query* matches a candidate exercise.

    Uses SequenceMatcher.ratio() on both the slug and the display name,
    with a boost for substring containment.  Returns the best score.
    """
    q_slug = _normalize(query)
    q_lower = query.strip().lower()

    slug_score = SequenceMatcher(None, q_slug, candidate_slug).ratio()
    display_score = SequenceMatcher(None, q_lower, candidate_display.lower()).ratio()
    score = max(slug_score, display_score)

    # Boost substring containment (e.g. "pull" matches "pull_up")
    if q_slug in candidate_slug or q_slug in candidate_display.lower():
        score = max(score, 0.85)

    return score


async def resolve_exercise(query: str, db: Database) -> Any:
    """Resolve a flexible exercise query to an exact exercise row.

    Strategy (single pipeline, no branching paths):
    1. Normalize the query → exact slug match (fast, common case)
    2. Score all exercises via SequenceMatcher
    3. Best match ≥ _AUTO_MATCH_CUTOFF → return it
    4. No good match → 404 with ranked suggestions
    """
    normalized = _normalize(query)

    # 1. Exact slug — fastest path, covers most tool calls.
    cursor = await db.execute(
        "SELECT * FROM exercises WHERE name = ? AND deleted_at IS NULL",
        (normalized,),
    )
    row = await cursor.fetchone()
    if row:
        return row

    # 2. Load catalog, score every exercise against the query.
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

    scored = [
        (ex, _score(query, ex["name"], ex["display_name"]))
        for ex in all_exercises
    ]
    scored.sort(key=lambda x: x[1], reverse=True)

    best_exercise, best_score = scored[0]

    logger.debug(
        "resolve_exercise(%r): best=%s score=%.3f",
        query, best_exercise["name"], best_score,
    )

    # 3. Accept the best match if it's strong enough.
    if best_score >= _AUTO_MATCH_CUTOFF:
        return best_exercise

    # 4. No match — return suggestions.
    suggestions = [
        ex["display_name"]
        for ex, s in scored[:5]
        if s >= _SUGGESTION_CUTOFF
    ]
    if not suggestions:
        suggestions = [ex["display_name"] for ex, _ in scored[:5]]

    raise HTTPException(
        status_code=404,
        detail={
            "error": "EXERCISE_NOT_FOUND",
            "query": query,
            "message": f"No exercise matching '{query}'. Did you mean one of these?",
            "suggestions": suggestions,
        },
    )
