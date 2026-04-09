"""Start the FastAPI server for athlete training tracking.

Honors the PORT env var (set by hosts like Render, Heroku, Fly).
Reload is only enabled in local dev (when ATHLETE_DEV=1).
"""

import os
import sys
from pathlib import Path

# Ensure src/ is on the path when running directly
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import uvicorn

from athlete_mcp.config import settings


if __name__ == "__main__":
    # Hosts like Render inject PORT — prefer it over our default.
    port = int(os.getenv("PORT", settings.API_PORT))
    host = os.getenv("HOST", settings.API_HOST)
    reload = os.getenv("ATHLETE_DEV", "").lower() in ("1", "true", "yes")

    uvicorn.run(
        "athlete_mcp.api.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level=settings.LOG_LEVEL.lower(),
    )
