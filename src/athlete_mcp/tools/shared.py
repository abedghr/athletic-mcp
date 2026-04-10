import json
import logging
from typing import Any

import httpx

from athlete_mcp.config import settings

logger = logging.getLogger(__name__)


def get_client() -> httpx.AsyncClient:
    """Create an httpx client per-request to avoid event loop issues with MCP stdio.

    When MCP_API_KEY is set, automatically include the bearer token so the
    in-process MCP tools can hit the auth-protected REST API without the
    user having to know about the key.
    """
    headers = {"Content-Type": "application/json"}
    if settings.MCP_API_KEY:
        headers["Authorization"] = f"Bearer {settings.MCP_API_KEY}"
    return httpx.AsyncClient(
        base_url=settings.API_BASE_URL,
        timeout=10.0,
        headers=headers,
    )


async def safe_api_call(
    method: str, path: str, **kwargs: Any
) -> dict:
    """Make an HTTP call to the FastAPI server with error handling.

    Returns a dict with 'success' key always present.
    """
    try:
        async with get_client() as client:
            response = await getattr(client, method)(path, **kwargs)

            if response.status_code == 404:
                detail = response.json().get("detail", {})
                if isinstance(detail, dict):
                    return {
                        "success": False,
                        "error_code": detail.get("error", "NOT_FOUND"),
                        "message": detail.get("message", "Not found"),
                        "suggestions": detail.get("suggestions", []),
                    }
                return {
                    "success": False,
                    "error_code": "NOT_FOUND",
                    "message": str(detail),
                    "suggestions": [],
                }

            if response.status_code == 422:
                detail = response.json().get("detail", [])
                messages = []
                for err in detail if isinstance(detail, list) else [detail]:
                    if isinstance(err, dict):
                        loc = " → ".join(str(l) for l in err.get("loc", []))
                        messages.append(f"{loc}: {err.get('msg', '')}")
                    else:
                        messages.append(str(err))
                return {
                    "success": False,
                    "error_code": "VALIDATION_ERROR",
                    "message": "Validation failed: " + "; ".join(messages),
                    "suggestions": [],
                }

            response.raise_for_status()
            data = response.json()
            return {"success": True, "data": data}

    except httpx.ConnectError:
        return {
            "success": False,
            "error_code": "API_UNAVAILABLE",
            "message": "Training API is not running. Start it with: python scripts/run_api.py",
            "suggestions": [],
        }
    except httpx.TimeoutException:
        return {
            "success": False,
            "error_code": "TIMEOUT",
            "message": "API request timed out. The server may be overloaded.",
            "suggestions": [],
        }
    except Exception as e:
        logger.exception("API call failed: %s %s", method, path)
        return {
            "success": False,
            "error_code": "INTERNAL_ERROR",
            "message": str(e),
            "suggestions": [],
        }


def format_tool_response(result: dict) -> str:
    """Format a tool result dict as a JSON string for MCP."""
    return json.dumps(result, indent=2, default=str)
