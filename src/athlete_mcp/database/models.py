from dataclasses import dataclass


@dataclass(slots=True)
class ExerciseRow:
    id: int
    name: str
    display_name: str
    category: str
    muscle_groups: str | None
    equipment: str | None
    tracking_type: str
    is_weighted: bool
    weight_unit: str
    description: str | None
    created_at: str
    updated_at: str
    deleted_at: str | None


@dataclass(slots=True)
class WorkoutRow:
    id: int
    date: str
    title: str | None
    bodyweight_kg: float | None
    location: str | None
    notes: str | None
    rating: int | None
    duration_mins: int | None
    created_at: str
    updated_at: str
    deleted_at: str | None


@dataclass(slots=True)
class SetRow:
    id: int
    workout_id: int
    exercise_id: int
    exercise_name: str
    exercise_display_name: str
    set_number: int
    reps: int | None
    duration_secs: int | None
    distance_m: float | None
    bodyweight_kg: float | None
    added_weight_kg: float
    rpe: float | None
    notes: str | None
    created_at: str
    updated_at: str
    deleted_at: str | None


@dataclass(slots=True)
class PersonalRecordRow:
    id: int
    exercise_id: int
    exercise_name: str
    pr_type: str
    value: float
    set_id: int | None
    date_achieved: str
    previous_value: float | None
    improvement_pct: float | None
    created_at: str


@dataclass(slots=True)
class BodyweightLogRow:
    id: int
    date: str
    weight_kg: float
    time_of_day: str
    notes: str | None
    created_at: str
