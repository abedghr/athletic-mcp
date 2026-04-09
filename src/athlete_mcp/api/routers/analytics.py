from datetime import date, timedelta

from fastapi import APIRouter, Query

from athlete_mcp.api.dependencies import DbDep, resolve_exercise
from athlete_mcp.api.schemas.analytics import (
    BodyweightEntry,
    BodyweightTrendResponse,
    DaySummary,
    ExerciseHistoryResponse,
    ExerciseSessionDetail,
    ExerciseStatsResponse,
    FrequencyItem,
    FrequencyResponse,
    PersonalRecordResponse,
    PlateauExercise,
    PlateauResponse,
    VolumeTrendResponse,
    WeekStats,
    WeekVolume,
    WeeklySummaryResponse,
)

router = APIRouter()


def _get_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


async def _week_stats(db, week_start: str, week_end: str) -> tuple[WeekStats, list[DaySummary]]:
    cursor = await db.execute(
        """SELECT w.date, s.exercise_display_name, s.exercise_name,
                  COUNT(s.id) as set_count,
                  SUM(COALESCE(s.reps, 0)) as total_reps,
                  SUM(COALESCE(s.reps, 0) * (COALESCE(s.bodyweight_kg, 0) + s.added_weight_kg)) as volume_kg,
                  AVG(s.rpe) as avg_rpe
           FROM sets s
           JOIN workouts w ON w.id = s.workout_id
           WHERE w.date BETWEEN ? AND ?
             AND s.deleted_at IS NULL AND w.deleted_at IS NULL
           GROUP BY w.date, s.exercise_name
           ORDER BY w.date, s.exercise_display_name""",
        (week_start, week_end),
    )
    rows = await cursor.fetchall()

    # Build day summaries
    days_map: dict[str, list] = {}
    unique_exercises = set()
    total_sets = 0
    total_reps = 0
    total_volume = 0.0
    rpe_values = []

    for row in rows:
        d = row["date"]
        if d not in days_map:
            days_map[d] = []
        days_map[d].append({
            "exercise": row["exercise_display_name"],
            "sets": row["set_count"],
            "reps": row["total_reps"],
            "volume_kg": round(row["volume_kg"] or 0, 2),
            "avg_rpe": round(row["avg_rpe"], 1) if row["avg_rpe"] else None,
        })
        unique_exercises.add(row["exercise_name"])
        total_sets += row["set_count"]
        total_reps += row["total_reps"] or 0
        total_volume += row["volume_kg"] or 0
        if row["avg_rpe"]:
            rpe_values.append(row["avg_rpe"])

    days = [
        DaySummary(
            date=d,
            exercises=exercises,
            total_sets=sum(e["sets"] for e in exercises),
            total_reps=sum(e["reps"] for e in exercises),
            total_volume_kg=round(sum(e["volume_kg"] for e in exercises), 2),
            avg_rpe=round(sum(r for r in [e["avg_rpe"] for e in exercises] if r) / max(len([e for e in exercises if e["avg_rpe"]]), 1), 1) if any(e["avg_rpe"] for e in exercises) else None,
        )
        for d, exercises in sorted(days_map.items())
    ]

    stats = WeekStats(
        total_sessions=len(days_map),
        total_sets=total_sets,
        total_reps=total_reps,
        total_volume_kg=round(total_volume, 2),
        unique_exercises=len(unique_exercises),
        avg_rpe=round(sum(rpe_values) / len(rpe_values), 1) if rpe_values else None,
    )
    return stats, days


@router.get("/prs", response_model=list[PersonalRecordResponse])
async def get_all_prs(db: DbDep, exercise: str | None = None):
    if exercise:
        ex = await resolve_exercise(exercise, db)
        cursor = await db.execute(
            """SELECT pr.*, e.display_name as exercise_display_name
               FROM personal_records pr
               JOIN exercises e ON e.id = pr.exercise_id
               WHERE pr.exercise_name = ?
               ORDER BY pr.pr_type""",
            (ex["name"],),
        )
    else:
        cursor = await db.execute(
            """SELECT pr.*, e.display_name as exercise_display_name
               FROM personal_records pr
               JOIN exercises e ON e.id = pr.exercise_id
               ORDER BY pr.exercise_name, pr.pr_type"""
        )

    rows = await cursor.fetchall()
    today = date.today()
    results = []
    for row in rows:
        days_since = (today - date.fromisoformat(row["date_achieved"])).days
        results.append(PersonalRecordResponse(
            exercise_name=row["exercise_name"],
            exercise_display_name=row["exercise_display_name"],
            pr_type=row["pr_type"],
            value=row["value"],
            date_achieved=row["date_achieved"],
            days_since_pr=days_since,
            previous_value=row["previous_value"],
            improvement_pct=row["improvement_pct"],
            set_id=row["set_id"],
        ))
    return results


@router.get("/prs/{exercise}", response_model=list[PersonalRecordResponse])
async def get_exercise_prs(exercise: str, db: DbDep):
    return await get_all_prs(db, exercise=exercise)


@router.get("/weekly-summary", response_model=WeeklySummaryResponse)
async def weekly_summary(db: DbDep, week_offset: int = Query(default=0, ge=-52, le=0)):
    today = date.today()
    target_monday = _get_monday(today + timedelta(weeks=week_offset))
    target_sunday = target_monday + timedelta(days=6)

    current_stats, days = await _week_stats(
        db, target_monday.isoformat(), target_sunday.isoformat()
    )

    # Previous week for comparison
    prev_monday = target_monday - timedelta(weeks=1)
    prev_sunday = prev_monday + timedelta(days=6)
    prev_stats, _ = await _week_stats(
        db, prev_monday.isoformat(), prev_sunday.isoformat()
    )

    deltas = None
    if prev_stats.total_sets > 0:
        deltas = {
            "sessions": current_stats.total_sessions - prev_stats.total_sessions,
            "sets": current_stats.total_sets - prev_stats.total_sets,
            "reps": current_stats.total_reps - prev_stats.total_reps,
            "volume_kg": round(current_stats.total_volume_kg - prev_stats.total_volume_kg, 2),
            "exercises": current_stats.unique_exercises - prev_stats.unique_exercises,
        }

    return WeeklySummaryResponse(
        week_start=target_monday.isoformat(),
        week_end=target_sunday.isoformat(),
        current_week=current_stats,
        previous_week=prev_stats if prev_stats.total_sets > 0 else None,
        days=days,
        deltas=deltas,
    )


@router.get("/exercise/{exercise}/history", response_model=ExerciseHistoryResponse)
async def exercise_history(exercise: str, db: DbDep, limit: int = Query(default=20, ge=1, le=100)):
    ex = await resolve_exercise(exercise, db)

    cursor = await db.execute(
        """SELECT s.*, w.date as workout_date
           FROM sets s
           JOIN workouts w ON w.id = s.workout_id
           WHERE s.exercise_name = ? AND s.deleted_at IS NULL AND w.deleted_at IS NULL
           ORDER BY w.date DESC, s.set_number""",
        (ex["name"],),
    )
    rows = await cursor.fetchall()

    # Group by workout
    sessions_map: dict[int, dict] = {}
    for row in rows:
        wid = row["workout_id"]
        if wid not in sessions_map:
            sessions_map[wid] = {
                "date": row["workout_date"],
                "workout_id": wid,
                "sets": [],
                "total_reps": 0,
                "max_weight_kg": 0,
                "total_volume_kg": 0,
                "rpe_values": [],
            }
        s = sessions_map[wid]
        bw = row["bodyweight_kg"] or 0
        added = row["added_weight_kg"] or 0
        total_w = bw + added if bw else added
        vol = (row["reps"] * total_w) if (row["reps"] and total_w) else 0

        s["sets"].append({
            "set_number": row["set_number"],
            "reps": row["reps"],
            "duration_secs": row["duration_secs"],
            "distance_m": row["distance_m"],
            "added_weight_kg": added,
            "total_weight_kg": total_w if total_w else None,
            "rpe": row["rpe"],
        })
        s["total_reps"] += row["reps"] or 0
        s["max_weight_kg"] = max(s["max_weight_kg"], added)
        s["total_volume_kg"] += vol
        if row["rpe"]:
            s["rpe_values"].append(row["rpe"])

    sessions = []
    for s in list(sessions_map.values())[:limit]:
        sessions.append(ExerciseSessionDetail(
            date=s["date"],
            workout_id=s["workout_id"],
            sets=s["sets"],
            total_reps=s["total_reps"],
            max_weight_kg=round(s["max_weight_kg"], 2),
            total_volume_kg=round(s["total_volume_kg"], 2),
            avg_rpe=round(sum(s["rpe_values"]) / len(s["rpe_values"]), 1) if s["rpe_values"] else None,
        ))

    return ExerciseHistoryResponse(
        exercise_name=ex["name"],
        exercise_display_name=ex["display_name"],
        sessions=sessions,
        total_sessions=len(sessions),
    )


@router.get("/exercise/{exercise}/stats", response_model=ExerciseStatsResponse)
async def exercise_stats(exercise: str, db: DbDep, period_days: int = Query(default=30, ge=1, le=365)):
    ex = await resolve_exercise(exercise, db)
    since = (date.today() - timedelta(days=period_days)).isoformat()

    cursor = await db.execute(
        """SELECT s.*, w.date as workout_date
           FROM sets s
           JOIN workouts w ON w.id = s.workout_id
           WHERE s.exercise_name = ? AND s.deleted_at IS NULL AND w.deleted_at IS NULL
             AND w.date >= ?
           ORDER BY w.date""",
        (ex["name"], since),
    )
    rows = await cursor.fetchall()

    if not rows:
        return ExerciseStatsResponse(
            exercise_name=ex["name"],
            exercise_display_name=ex["display_name"],
            period_days=period_days,
        )

    workout_ids = set()
    total_reps = 0
    total_volume = 0.0
    max_reps = 0
    max_weight = 0.0
    rpe_values = []

    for row in rows:
        workout_ids.add(row["workout_id"])
        reps = row["reps"] or 0
        added = row["added_weight_kg"] or 0
        bw = row["bodyweight_kg"] or 0
        total_w = bw + added if bw else added

        total_reps += reps
        if reps > max_reps:
            max_reps = reps
        if added > max_weight:
            max_weight = added
        total_volume += reps * total_w if total_w else 0
        if row["rpe"]:
            rpe_values.append(row["rpe"])

    total_sets = len(rows)
    avg_reps = round(total_reps / total_sets, 1) if total_sets else None

    # Simple trend: compare first half to second half of sets
    trend = None
    if total_sets >= 4:
        mid = total_sets // 2
        first_half_reps = sum((r["reps"] or 0) for r in rows[:mid])
        second_half_reps = sum((r["reps"] or 0) for r in rows[mid:])
        if first_half_reps > 0:
            change = ((second_half_reps - first_half_reps) / first_half_reps) * 100
            if change > 5:
                trend = "improving"
            elif change < -5:
                trend = "declining"
            else:
                trend = "stable"

    return ExerciseStatsResponse(
        exercise_name=ex["name"],
        exercise_display_name=ex["display_name"],
        period_days=period_days,
        total_sessions=len(workout_ids),
        total_sets=total_sets,
        total_reps=total_reps,
        total_volume_kg=round(total_volume, 2),
        max_reps_single_set=max_reps if max_reps else None,
        max_weight_kg=max_weight if max_weight else None,
        avg_reps_per_set=avg_reps,
        avg_rpe=round(sum(rpe_values) / len(rpe_values), 1) if rpe_values else None,
        trend=trend,
    )


@router.get("/plateaus", response_model=PlateauResponse)
async def detect_plateaus(
    db: DbDep,
    window_weeks: int = Query(default=4, ge=2, le=26),
    threshold_pct: float = Query(default=5.0, ge=0, le=50),
):
    since = (date.today() - timedelta(weeks=window_weeks)).isoformat()
    midpoint = (date.today() - timedelta(weeks=window_weeks // 2)).isoformat()

    # Get all exercises with sessions in the window
    cursor = await db.execute(
        """SELECT s.exercise_id, s.exercise_name, s.exercise_display_name, w.date,
                  MAX(s.reps) as max_reps,
                  MAX(s.added_weight_kg) as max_weight,
                  SUM(COALESCE(s.reps, 0) * (COALESCE(s.bodyweight_kg, 0) + s.added_weight_kg)) as volume
           FROM sets s
           JOIN workouts w ON w.id = s.workout_id
           WHERE w.date >= ? AND s.deleted_at IS NULL AND w.deleted_at IS NULL
           GROUP BY s.exercise_name, w.date
           ORDER BY s.exercise_name, w.date""",
        (since,),
    )
    rows = await cursor.fetchall()

    # Group by exercise
    exercise_sessions: dict[str, list] = {}
    exercise_meta: dict[str, dict] = {}
    for row in rows:
        name = row["exercise_name"]
        if name not in exercise_sessions:
            exercise_sessions[name] = []
            exercise_meta[name] = {
                "display_name": row["exercise_display_name"],
                "exercise_id": row["exercise_id"],
            }
        exercise_sessions[name].append(row)

    plateaued = []
    improving = []
    insufficient_data = []

    for name, sessions in exercise_sessions.items():
        meta = exercise_meta[name]
        if len(sessions) < 4:
            insufficient_data.append({
                "exercise_name": name,
                "exercise_display_name": meta["display_name"],
                "sessions": len(sessions),
            })
            continue

        # Split into first and second half
        first_half = [s for s in sessions if s["date"] < midpoint]
        second_half = [s for s in sessions if s["date"] >= midpoint]

        if not first_half or not second_half:
            insufficient_data.append({
                "exercise_name": name,
                "exercise_display_name": meta["display_name"],
                "sessions": len(sessions),
            })
            continue

        # Compare average max reps or volume
        first_avg = sum(s["max_reps"] or s["volume"] or 0 for s in first_half) / len(first_half)
        second_avg = sum(s["max_reps"] or s["volume"] or 0 for s in second_half) / len(second_half)

        if first_avg > 0:
            change_pct = ((second_avg - first_avg) / first_avg) * 100
        else:
            change_pct = 0

        if change_pct < threshold_pct:
            # Determine suggested action
            if window_weeks >= 6:
                suggested = "deload_week then change_variation"
            elif change_pct < 0:
                suggested = "drop_sets_increase_weight or pause_reps"
            else:
                suggested = "add_weight or increase_reps"

            plateaued.append(PlateauExercise(
                exercise_name=name,
                exercise_display_name=meta["display_name"],
                sessions_in_window=len(sessions),
                first_half_avg=round(first_avg, 2),
                second_half_avg=round(second_avg, 2),
                change_pct=round(change_pct, 1),
                suggested_action=suggested,
            ))
        else:
            improving.append({
                "exercise_name": name,
                "exercise_display_name": meta["display_name"],
                "change_pct": round(change_pct, 1),
                "sessions": len(sessions),
            })

    return PlateauResponse(
        window_weeks=window_weeks,
        threshold_pct=threshold_pct,
        plateaued=plateaued,
        improving=improving,
        insufficient_data=insufficient_data,
    )


@router.get("/frequency", response_model=FrequencyResponse)
async def training_frequency(db: DbDep, period_days: int = Query(default=30, ge=1, le=365)):
    since = (date.today() - timedelta(days=period_days)).isoformat()
    today_str = date.today().isoformat()

    cursor = await db.execute(
        """SELECT s.exercise_name, s.exercise_display_name, e.category,
                  COUNT(DISTINCT w.id) as session_count,
                  COUNT(s.id) as total_sets,
                  MAX(w.date) as last_performed
           FROM sets s
           JOIN workouts w ON w.id = s.workout_id
           JOIN exercises e ON e.id = s.exercise_id
           WHERE w.date >= ? AND s.deleted_at IS NULL AND w.deleted_at IS NULL
           GROUP BY s.exercise_name
           ORDER BY session_count DESC""",
        (since,),
    )
    rows = await cursor.fetchall()

    exercises = []
    by_category: dict[str, int] = {}
    for row in rows:
        days_since = (date.fromisoformat(today_str) - date.fromisoformat(row["last_performed"])).days
        exercises.append(FrequencyItem(
            exercise_name=row["exercise_name"],
            exercise_display_name=row["exercise_display_name"],
            category=row["category"],
            session_count=row["session_count"],
            total_sets=row["total_sets"],
            last_performed=row["last_performed"],
            days_since_last=days_since,
        ))
        by_category[row["category"]] = by_category.get(row["category"], 0) + row["session_count"]

    return FrequencyResponse(
        period_days=period_days,
        exercises=exercises,
        by_category=by_category,
    )


@router.get("/bodyweight", response_model=BodyweightTrendResponse)
async def bodyweight_trend(db: DbDep, limit: int = Query(default=30, ge=1, le=365)):
    cursor = await db.execute(
        "SELECT * FROM bodyweight_log ORDER BY date DESC LIMIT ?", (limit,)
    )
    rows = await cursor.fetchall()

    if not rows:
        return BodyweightTrendResponse()

    entries = [
        BodyweightEntry(
            date=row["date"],
            weight_kg=row["weight_kg"],
            time_of_day=row["time_of_day"],
            notes=row["notes"],
        )
        for row in reversed(rows)
    ]

    weights = [e.weight_kg for e in entries]
    current = weights[-1]
    trend = None
    if len(weights) >= 3:
        first_third = sum(weights[: len(weights) // 3]) / (len(weights) // 3)
        last_third = sum(weights[-(len(weights) // 3) :]) / (len(weights) // 3)
        diff = last_third - first_third
        if diff > 0.5:
            trend = "gaining"
        elif diff < -0.5:
            trend = "losing"
        else:
            trend = "stable"

    return BodyweightTrendResponse(
        entries=entries,
        current_weight_kg=current,
        min_weight_kg=min(weights),
        max_weight_kg=max(weights),
        avg_weight_kg=round(sum(weights) / len(weights), 2),
        trend=trend,
    )


@router.post("/bodyweight", status_code=201)
async def log_bodyweight(
    db: DbDep,
    weight_kg: float = Query(ge=20, le=300),
    date_str: str | None = None,
    time_of_day: str = "morning",
    notes: str | None = None,
):
    log_date = date_str or date.today().isoformat()
    try:
        await db.execute(
            """INSERT INTO bodyweight_log (date, weight_kg, time_of_day, notes)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET weight_kg = ?, time_of_day = ?, notes = ?""",
            (log_date, weight_kg, time_of_day, notes, weight_kg, time_of_day, notes),
        )
        await db.commit()
    except Exception:
        await db.execute(
            "UPDATE bodyweight_log SET weight_kg = ?, time_of_day = ?, notes = ? WHERE date = ?",
            (weight_kg, time_of_day, notes, log_date),
        )
        await db.commit()

    return {
        "message": f"Bodyweight logged: {weight_kg}kg on {log_date}",
        "date": log_date,
        "weight_kg": weight_kg,
    }


@router.get("/volume-trend", response_model=VolumeTrendResponse)
async def volume_trend(db: DbDep, weeks: int = Query(default=8, ge=1, le=52)):
    since = (date.today() - timedelta(weeks=weeks)).isoformat()

    cursor = await db.execute(
        """SELECT w.date,
                  SUM(COALESCE(s.reps, 0) * (COALESCE(s.bodyweight_kg, 0) + s.added_weight_kg)) as volume,
                  COUNT(s.id) as set_count,
                  SUM(COALESCE(s.reps, 0)) as rep_count
           FROM sets s
           JOIN workouts w ON w.id = s.workout_id
           WHERE w.date >= ? AND s.deleted_at IS NULL AND w.deleted_at IS NULL
           GROUP BY w.date
           ORDER BY w.date""",
        (since,),
    )
    rows = await cursor.fetchall()

    # Group by week
    weeks_map: dict[str, dict] = {}
    for row in rows:
        d = date.fromisoformat(row["date"])
        monday = _get_monday(d).isoformat()
        if monday not in weeks_map:
            weeks_map[monday] = {"volume": 0, "sets": 0, "reps": 0}
        weeks_map[monday]["volume"] += row["volume"] or 0
        weeks_map[monday]["sets"] += row["set_count"]
        weeks_map[monday]["reps"] += row["rep_count"] or 0

    data = [
        WeekVolume(
            week_start=ws,
            total_volume_kg=round(v["volume"], 2),
            total_sets=v["sets"],
            total_reps=v["reps"],
        )
        for ws, v in sorted(weeks_map.items())
    ]

    trend = None
    if len(data) >= 3:
        first = data[0].total_volume_kg
        last = data[-1].total_volume_kg
        if first > 0:
            pct = ((last - first) / first) * 100
            if pct > 10:
                trend = "increasing"
            elif pct < -10:
                trend = "decreasing"
            else:
                trend = "stable"

    return VolumeTrendResponse(weeks=weeks, data=data, trend=trend)
