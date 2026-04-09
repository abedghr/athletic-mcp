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
    # Hosts like Render inject PORT — prefer it over our default for the
    # in-process loopback URL the MCP tools use. ATHLETE_API_PORT can still
    # override if explicitly set.
    API_PORT: int = int(os.getenv("ATHLETE_API_PORT") or os.getenv("PORT") or "8000")
    # Loopback URL the MCP tools call. Defaults to localhost on whichever port
    # the API is actually bound to. Override with ATHLETE_API_BASE_URL only if
    # the MCP tools should reach the API over a different network.
    API_BASE_URL: str = os.getenv(
        "ATHLETE_API_BASE_URL",
        f"http://localhost:{int(os.getenv('ATHLETE_API_PORT') or os.getenv('PORT') or '8000')}",
    )

    # Auth — required for remote deploys, optional for local
    MCP_API_KEY: str | None = os.getenv("MCP_API_KEY")

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    @property
    def using_turso(self) -> bool:
        return bool(self.TURSO_DATABASE_URL)


settings = Settings()
