from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # Local SQLite path (used when TURSO_DATABASE_URL is not set)
    DB_PATH: Path = Path(
        os.getenv("ATHLETE_DB_PATH", str(Path.home() / ".athlete" / "training.db"))
    )

    # Turso (libsql) — when set, takes precedence over DB_PATH
    TURSO_DATABASE_URL: str | None = os.getenv("TURSO_DATABASE_URL")
    TURSO_AUTH_TOKEN: str | None = os.getenv("TURSO_AUTH_TOKEN")

    # API
    API_HOST: str = os.getenv("ATHLETE_API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("ATHLETE_API_PORT", "8000"))
    API_BASE_URL: str = os.getenv("ATHLETE_API_BASE_URL", "http://localhost:8000")

    # Auth — required for remote deploys, optional for local
    MCP_API_KEY: str | None = os.getenv("MCP_API_KEY")

    # Athlete profile
    DEFAULT_BODYWEIGHT_KG: float | None = (
        float(os.getenv("DEFAULT_BODYWEIGHT_KG"))
        if os.getenv("DEFAULT_BODYWEIGHT_KG")
        else None
    )
    ATHLETE_NAME: str = os.getenv("ATHLETE_NAME", "Athlete")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    @property
    def using_turso(self) -> bool:
        return bool(self.TURSO_DATABASE_URL)


settings = Settings()
