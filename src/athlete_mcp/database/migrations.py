import logging

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    applied_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS exercises (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    display_name    TEXT NOT NULL,
    category        TEXT NOT NULL,
    muscle_groups   TEXT,
    equipment       TEXT,
    tracking_type   TEXT NOT NULL DEFAULT 'reps',
    is_weighted     BOOLEAN NOT NULL DEFAULT 1,
    weight_unit     TEXT NOT NULL DEFAULT 'kg',
    description     TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at      TIMESTAMP NULL
);

CREATE TABLE IF NOT EXISTS athlete_profile (
    id              INTEGER PRIMARY KEY DEFAULT 1,
    name            TEXT,
    sport           TEXT,
    bodyweight_kg   REAL,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS workouts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            TEXT NOT NULL,
    title           TEXT,
    bodyweight_kg   REAL,
    location        TEXT,
    notes           TEXT,
    rating          INTEGER CHECK(rating BETWEEN 1 AND 5),
    duration_mins   INTEGER,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at      TIMESTAMP NULL
);

CREATE TABLE IF NOT EXISTS sets (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    workout_id              INTEGER NOT NULL REFERENCES workouts(id) ON DELETE CASCADE,
    exercise_id             INTEGER NOT NULL REFERENCES exercises(id),
    exercise_name           TEXT NOT NULL,
    exercise_display_name   TEXT NOT NULL,
    set_number              INTEGER NOT NULL,
    reps                    INTEGER,
    duration_secs           INTEGER,
    distance_m              REAL,
    bodyweight_kg           REAL,
    added_weight_kg         REAL NOT NULL DEFAULT 0,
    rpe                     REAL CHECK(rpe BETWEEN 1 AND 10),
    notes                   TEXT,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at              TIMESTAMP NULL
);

CREATE TABLE IF NOT EXISTS bodyweight_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT NOT NULL UNIQUE,
    weight_kg   REAL NOT NULL,
    time_of_day TEXT DEFAULT 'morning',
    notes       TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS personal_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    exercise_id     INTEGER NOT NULL REFERENCES exercises(id),
    exercise_name   TEXT NOT NULL,
    pr_type         TEXT NOT NULL,
    value           REAL NOT NULL,
    set_id          INTEGER REFERENCES sets(id),
    date_achieved   TEXT NOT NULL,
    previous_value  REAL,
    improvement_pct REAL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(exercise_name, pr_type)
);

CREATE INDEX IF NOT EXISTS idx_sets_workout ON sets(workout_id, deleted_at);
CREATE INDEX IF NOT EXISTS idx_sets_exercise ON sets(exercise_id, deleted_at);
CREATE INDEX IF NOT EXISTS idx_workouts_date ON workouts(date, deleted_at);
CREATE INDEX IF NOT EXISTS idx_personal_records_exercise ON personal_records(exercise_id);
"""

# (name, display_name, category, tracking_type, is_weighted, equipment)
DEFAULT_EXERCISES = [
    # Calisthenics — Pull
    ("pull_up", "Pull Up", "pull", "reps", True, "bar"),
    ("chin_up", "Chin Up", "pull", "reps", True, "bar"),
    ("archer_pull_up", "Archer Pull Up", "pull", "reps", True, "bar"),
    ("front_lever", "Front Lever", "pull", "duration", False, "bar"),
    ("back_lever", "Back Lever", "pull", "duration", False, "bar"),
    ("muscle_up", "Muscle Up", "full_body", "reps", True, "bar"),
    ("ring_muscle_up", "Ring Muscle Up", "full_body", "reps", True, "rings"),
    # Calisthenics — Push
    ("dip", "Dip", "push", "reps", True, "bar"),
    ("straight_bar_dip", "Straight Bar Dip", "push", "reps", True, "bar"),
    ("push_up", "Push Up", "push", "reps", True, "bodyweight"),
    ("pike_push_up", "Pike Push Up", "push", "reps", True, "bodyweight"),
    ("handstand_push_up", "Handstand Push Up", "push", "reps", True, "bodyweight"),
    ("ring_dip", "Ring Dip", "push", "reps", True, "rings"),
    # Calisthenics — Core
    ("plank", "Plank", "core", "duration", False, "bodyweight"),
    ("leg_raise", "Leg Raise", "core", "reps", False, "bar"),
    ("toes_to_bar", "Toes To Bar", "core", "reps", False, "bar"),
    ("l_sit", "L-Sit", "isometric", "duration", False, "bodyweight"),
    ("dragon_flag", "Dragon Flag", "core", "reps", False, "bodyweight"),
    # Calisthenics — Legs
    ("pistol_squat", "Pistol Squat", "legs", "reps", True, "bodyweight"),
    ("jump_squat", "Jump Squat", "legs", "reps", False, "bodyweight"),
    # Barbell
    ("squat", "Squat", "legs", "reps", True, "barbell"),
    ("deadlift", "Deadlift", "full_body", "reps", True, "barbell"),
    ("bench_press", "Bench Press", "push", "reps", True, "barbell"),
    ("overhead_press", "Overhead Press", "push", "reps", True, "barbell"),
    # Cardio
    ("run", "Run", "cardio", "distance", False, "none"),
    ("row", "Row (Machine)", "cardio", "distance", False, "machine"),
]


async def run_migrations(db) -> None:
    # Check if we already applied the initial migration. If schema_migrations
    # doesn't exist yet, the SELECT will raise — we catch broadly because
    # different drivers raise different exception types.
    try:
        cursor = await db.execute(
            "SELECT version FROM schema_migrations WHERE version = 1"
        )
        row = await cursor.fetchone()
        if row is not None:
            logger.info("Migrations already applied")
            return
    except Exception:
        # schema_migrations table doesn't exist yet — proceed
        pass

    logger.info("Running initial migration...")
    await db.executescript(SCHEMA_SQL)

    # Record migration
    await db.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (1, 'initial_schema')"
    )

    # Seed exercises if table is empty
    cursor = await db.execute("SELECT COUNT(*) FROM exercises")
    row = await cursor.fetchone()
    if row[0] == 0:
        logger.info("Seeding %d default exercises", len(DEFAULT_EXERCISES))
        await db.executemany(
            "INSERT INTO exercises (name, display_name, category, tracking_type, is_weighted, equipment) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            DEFAULT_EXERCISES,
        )

    await db.commit()
    logger.info("Initial migration complete")
