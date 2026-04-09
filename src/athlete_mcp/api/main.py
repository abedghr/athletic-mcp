import logging
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from athlete_mcp.api.auth import BearerAuthMiddleware
from athlete_mcp.api.routers import analytics, exercises, health, sets, workouts
from athlete_mcp.config import settings
from athlete_mcp.database.connection import close_db, init_db
from athlete_mcp.servers.analytics_server import get_http_app as get_analytics_app
from athlete_mcp.servers.logger_server import get_http_app as get_logger_app

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# Build the MCP HTTP apps once at module load. Their lifespans must be
# entered when FastAPI starts so the StreamableHTTPSessionManager is alive.
_logger_mcp_app = get_logger_app()
_analytics_mcp_app = get_analytics_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Athlete Training API...")
    await init_db()
    if settings.using_turso:
        logger.info("API ready — Turso database")
    else:
        logger.info("API ready — local database at %s", settings.DB_PATH)

    # Mounted Starlette sub-apps don't get their lifespan run automatically.
    # Enter both MCP app lifespans manually so the session managers start.
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(_logger_mcp_app.router.lifespan_context(_logger_mcp_app))
        await stack.enter_async_context(_analytics_mcp_app.router.lifespan_context(_analytics_mcp_app))
        logger.info("MCP HTTP transports ready at /mcp/logger and /mcp/analytics")
        yield

    await close_db()
    logger.info("API shut down")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Athlete Training API",
        version="1.0.0",
        description="Personal athletic performance tracking API + MCP servers",
        lifespan=lifespan,
    )

    # Auth middleware MUST be added before CORS so OPTIONS preflights bypass it.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(
        BearerAuthMiddleware,
        api_key=settings.MCP_API_KEY,
    )

    # REST API routers
    app.include_router(health.router, tags=["health"])
    app.include_router(exercises.router, prefix="/exercises", tags=["exercises"])
    app.include_router(workouts.router, prefix="/workouts", tags=["workouts"])
    app.include_router(sets.router, prefix="/sets", tags=["sets"])
    app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])

    # MCP HTTP endpoints — Claude Desktop / Custom Connectors will hit these.
    # The auth middleware above runs before the mount, so MCP requests
    # require Authorization: Bearer <MCP_API_KEY> just like the REST API.
    app.mount("/mcp/logger", _logger_mcp_app)
    app.mount("/mcp/analytics", _analytics_mcp_app)

    return app


app = create_app()
