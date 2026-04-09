from pydantic import BaseModel, Field
from typing import Optional


class ExerciseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Slug name: pull_up, bench_press")
    display_name: str = Field(..., min_length=1, max_length=200, description="Human-readable: Pull Up")
    category: str = Field(..., description="push|pull|core|legs|full_body|isometric|cardio|sport_specific")
    muscle_groups: Optional[str] = Field(None, description='JSON array: ["chest","triceps"]')
    equipment: Optional[str] = Field(None, description="bodyweight|barbell|dumbbell|rings|bar|machine|none")
    tracking_type: str = Field(default="reps", description="reps|duration|distance|rounds")
    is_weighted: bool = Field(default=True, description="Can external weight be added?")
    weight_unit: str = Field(default="kg", description="kg|lbs")
    description: Optional[str] = Field(None, max_length=1000)


class ExerciseUpdate(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=200)
    category: Optional[str] = None
    muscle_groups: Optional[str] = None
    equipment: Optional[str] = None
    tracking_type: Optional[str] = None
    is_weighted: Optional[bool] = None
    weight_unit: Optional[str] = None
    description: Optional[str] = None


class ExerciseResponse(BaseModel):
    id: int
    name: str
    display_name: str
    category: str
    muscle_groups: Optional[str] = None
    equipment: Optional[str] = None
    tracking_type: str
    is_weighted: bool
    weight_unit: str
    description: Optional[str] = None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class ExerciseSearchResult(BaseModel):
    exercise: ExerciseResponse
    score: float = Field(description="Match score 0-1")
