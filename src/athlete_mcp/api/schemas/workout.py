from pydantic import BaseModel, Field
from typing import Optional


class WorkoutCreate(BaseModel):
    date: Optional[str] = Field(None, description="YYYY-MM-DD, defaults to today")
    title: Optional[str] = Field(None, max_length=200)
    bodyweight_kg: Optional[float] = Field(None, ge=20, le=300)
    location: Optional[str] = Field(None, max_length=200)
    notes: Optional[str] = Field(None, max_length=2000)


class WorkoutUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    bodyweight_kg: Optional[float] = Field(None, ge=20, le=300)
    location: Optional[str] = Field(None, max_length=200)
    notes: Optional[str] = Field(None, max_length=2000)
    rating: Optional[int] = Field(None, ge=1, le=5)
    duration_mins: Optional[int] = Field(None, ge=0)


class WorkoutResponse(BaseModel):
    id: int
    date: str
    title: Optional[str] = None
    bodyweight_kg: Optional[float] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    rating: Optional[int] = None
    duration_mins: Optional[int] = None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class WorkoutWithSets(WorkoutResponse):
    sets: list[dict] = Field(default_factory=list, description="All sets in this workout")
    total_sets: int = 0
    total_volume_kg: Optional[float] = None
    exercises_performed: list[str] = Field(default_factory=list)
