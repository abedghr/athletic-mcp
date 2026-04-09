from athlete_mcp.api.schemas.exercise import (
    ExerciseCreate,
    ExerciseResponse,
    ExerciseUpdate,
)
from athlete_mcp.api.schemas.workout import (
    WorkoutCreate,
    WorkoutResponse,
    WorkoutUpdate,
    WorkoutWithSets,
)
from athlete_mcp.api.schemas.set import SetCreate, SetResponse
from athlete_mcp.api.schemas.analytics import (
    PersonalRecordResponse,
    WeeklySummaryResponse,
    ExerciseHistoryResponse,
    ExerciseStatsResponse,
    PlateauResponse,
    FrequencyResponse,
    BodyweightTrendResponse,
    VolumeTrendResponse,
)

__all__ = [
    "ExerciseCreate",
    "ExerciseResponse",
    "ExerciseUpdate",
    "WorkoutCreate",
    "WorkoutResponse",
    "WorkoutUpdate",
    "WorkoutWithSets",
    "SetCreate",
    "SetResponse",
    "PersonalRecordResponse",
    "WeeklySummaryResponse",
    "ExerciseHistoryResponse",
    "ExerciseStatsResponse",
    "PlateauResponse",
    "FrequencyResponse",
    "BodyweightTrendResponse",
    "VolumeTrendResponse",
]
