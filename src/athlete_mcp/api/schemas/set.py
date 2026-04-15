from pydantic import BaseModel, Field, model_validator
from typing import Optional


class SetCreate(BaseModel):
    exercise: str = Field(
        ..., min_length=1, max_length=200,
        description="Exercise name or display name — will be fuzzy matched",
    )
    workout_id: Optional[int] = Field(None, ge=1, description="If omitted, uses today's workout")
    date: Optional[str] = Field(
        None,
        description="ISO date (YYYY-MM-DD) the set was performed. Defaults to today. "
                    "Ignored when workout_id is provided.",
    )
    allow_old: bool = Field(
        default=False,
        description="Permit dates older than 90 days (safety flag for backlogging).",
    )
    reps: Optional[int] = Field(None, ge=1, le=1000)
    duration_secs: Optional[int] = Field(None, ge=1, le=86400)
    distance_m: Optional[float] = Field(None, ge=0, le=100_000)
    bodyweight_kg: Optional[float] = Field(None, ge=20, le=300)
    added_weight_kg: float = Field(default=0, ge=0, le=500)
    rpe: Optional[float] = Field(None, ge=1, le=10)
    notes: Optional[str] = Field(None, max_length=500)

    @model_validator(mode="after")
    def require_at_least_one_metric(self):
        if not any([self.reps, self.duration_secs, self.distance_m]):
            raise ValueError("At least one of reps, duration_secs, or distance_m is required")
        return self


class SetUpdate(BaseModel):
    reps: Optional[int] = Field(None, ge=1, le=1000)
    duration_secs: Optional[int] = Field(None, ge=1, le=86400)
    distance_m: Optional[float] = Field(None, ge=0, le=100_000)
    bodyweight_kg: Optional[float] = Field(None, ge=20, le=300)
    added_weight_kg: Optional[float] = Field(None, ge=0, le=500)
    rpe: Optional[float] = Field(None, ge=1, le=10)
    notes: Optional[str] = Field(None, max_length=500)


class PRInfo(BaseModel):
    pr_type: str
    new_value: float
    old_value: Optional[float] = None
    improvement_pct: Optional[float] = None


class SetResponse(BaseModel):
    id: int
    workout_id: int
    exercise_name: str
    exercise_display_name: str
    set_number: int
    reps: Optional[int] = None
    duration_secs: Optional[int] = None
    distance_m: Optional[float] = None
    bodyweight_kg: Optional[float] = None
    added_weight_kg: float
    total_weight_kg: Optional[float] = None
    volume_kg: Optional[float] = None
    rpe: Optional[float] = None
    notes: Optional[str] = None
    created_at: str
    new_pr: Optional[PRInfo] = None
