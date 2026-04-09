"""Bearer token authentication middleware.

When MCP_API_KEY is set, every request must include:
    Authorization: Bearer <key>

When MCP_API_KEY is not set (local dev), auth is disabled entirely.

Public paths (health, docs, openapi) are always allowed without auth.
"""

import logging
from collections.abc import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from athlete_mcp.config import settings

logger = logging.getLogger(__name__)

# Paths that never require auth — health checks, OpenAPI schema, Swagger UI.
PUBLIC_PATHS: frozenset[str] = frozenset({
    "/health",
    "/ready",
    "/",
    "/docs",
    "/redoc",
    "/openapi.json",
})


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Require `Authorization: Bearer <MCP_API_KEY>` on protected requests."""

    def __init__(self, app, api_key: str | None):
        super().__init__(app)
        self.api_key = api_key
        if not api_key:
            logger.warning(
                "MCP_API_KEY is not set — auth middleware is disabled. "
                "Do not run this in production without setting MCP_API_KEY."
            )

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable],
    ):
        # No key configured → auth disabled
        if not self.api_key:
            return await call_next(request)

        path = request.url.path

        # Always allow public paths
        if path in PUBLIC_PATHS:
            return await call_next(request)

        # Allow Swagger UI assets
        if path.startswith("/docs/") or path.startswith("/static/"):
            return await call_next(request)

        # Skip auth for MCP HTTP endpoints — they're protected by a URL-secret
        # capability path (/mcp/<key>/...) instead of bearer auth, because
        # Claude Custom Connectors don't support arbitrary auth headers.
        # Anyone hitting the wrong path gets a 404 from Starlette's router.
        if path.startswith("/mcp/"):
            return await call_next(request)

        # Check Authorization header
        auth_header = request.headers.get("authorization", "")
        if not auth_header.lower().startswith("bearer "):
            return JSONResponse(
                status_code=401,
                content={
                    "error": "UNAUTHORIZED",
                    "message": "Missing or invalid Authorization header. "
                               "Expected: Authorization: Bearer <api-key>",
                },
            )

        provided_key = auth_header[7:].strip()
        if provided_key != self.api_key:
            return JSONResponse(
                status_code=401,
                content={
                    "error": "UNAUTHORIZED",
                    "message": "Invalid API key.",
                },
            )

        return await call_next(request)


def get_auth_middleware():
    """Factory returning the middleware class and its kwargs."""
    return BearerAuthMiddleware, {"api_key": settings.MCP_API_KEY}
