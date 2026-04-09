from pydantic import BaseModel, Field
from typing import Optional


class PersonalRecordResponse(BaseModel):
    exercise_name: str
    exercise_display_name: str
    pr_type: str
    value: float
    date_achieved: str
    days_since_pr: int
    previous_value: Optional[float] = None
    improvement_pct: Optional[float] = None
    set_id: Optional[int] = None


class DaySummary(BaseModel):
    date: str
    exercises: list[dict] = Field(default_factory=list)
    total_sets: int = 0
    total_reps: int = 0
    total_volume_kg: float = 0
    avg_rpe: Optional[float] = None


class WeekStats(BaseModel):
    total_sessions: int = 0
    total_sets: int = 0
    total_reps: int = 0
    total_volume_kg: float = 0
    unique_exercises: int = 0
    avg_rpe: Optional[float] = None


class WeeklySummaryResponse(BaseModel):
    week_start: str
    week_end: str
    current_week: WeekStats
    previous_week: Optional[WeekStats] = None
    days: list[DaySummary] = Field(default_factory=list)
    deltas: Optional[dict] = None


class ExerciseSessionDetail(BaseModel):
    date: str
    workout_id: int
    sets: list[dict] = Field(default_factory=list)
    total_reps: int = 0
    max_weight_kg: float = 0
    total_volume_kg: float = 0
    avg_rpe: Optional[float] = None


class ExerciseHistoryResponse(BaseModel):
    exercise_name: str
    exercise_display_name: str
    sessions: list[ExerciseSessionDetail] = Field(default_factory=list)
    total_sessions: int = 0


class ExerciseStatsResponse(BaseModel):
    exercise_name: str
    exercise_display_name: str
    period_days: int
    total_sessions: int = 0
    total_sets: int = 0
    total_reps: int = 0
    total_volume_kg: float = 0
    max_reps_single_set: Optional[int] = None
    max_weight_kg: Optional[float] = None
    avg_reps_per_set: Optional[float] = None
    avg_rpe: Optional[float] = None
    trend: Optional[str] = None


class PlateauExercise(BaseModel):
    exercise_name: str
    exercise_display_name: str
    sessions_in_window: int
    first_half_avg: float
    second_half_avg: float
    change_pct: float
    suggested_action: str


class PlateauResponse(BaseModel):
    window_weeks: int
    threshold_pct: float
    plateaued: list[PlateauExercise] = Field(default_factory=list)
    improving: list[dict] = Field(default_factory=list)
    insufficient_data: list[dict] = Field(default_factory=list)


class FrequencyItem(BaseModel):
    exercise_name: str
    exercise_display_name: str
    category: str
    session_count: int
    total_sets: int
    last_performed: str
    days_since_last: int


class FrequencyResponse(BaseModel):
    period_days: int
    exercises: list[FrequencyItem] = Field(default_factory=list)
    by_category: dict[str, int] = Field(default_factory=dict)


class BodyweightEntry(BaseModel):
    date: str
    weight_kg: float
    time_of_day: str
    notes: Optional[str] = None


class BodyweightTrendResponse(BaseModel):
    entries: list[BodyweightEntry] = Field(default_factory=list)
    current_weight_kg: Optional[float] = None
    min_weight_kg: Optional[float] = None
    max_weight_kg: Optional[float] = None
    avg_weight_kg: Optional[float] = None
    trend: Optional[str] = None


class WeekVolume(BaseModel):
    week_start: str
    total_volume_kg: float
    total_sets: int
    total_reps: int


class VolumeTrendResponse(BaseModel):
    weeks: int
    data: list[WeekVolume] = Field(default_factory=list)
    trend: Optional[str] = None
