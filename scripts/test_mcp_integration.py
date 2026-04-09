"""MCP integration test — simulates Claude Desktop's JSON-RPC handshake.

Two modes:

1. STDIO (default) — spawns each MCP server as a subprocess and speaks
   JSON-RPC over stdio. Verifies the local stdio transport works.
   Requires the FastAPI server to be running on localhost:8000.

2. HTTP — connects to remote MCP HTTP endpoints (mounted at /mcp/logger
   and /mcp/analytics). Used to verify a deployed instance.

Mode selection:
    Default: stdio
    Set MCP_TEST_MODE=http to use HTTP mode.
    Set ATHLETE_API_BASE_URL=https://your-host (default http://localhost:8000)
    Set MCP_API_KEY=your-key (required when the deployed API has auth)

Examples:
    # Local stdio test
    python3 scripts/test_mcp_integration.py

    # Remote HTTP test against Render deploy
    MCP_TEST_MODE=http \\
    ATHLETE_API_BASE_URL=https://athlete-mcp.onrender.com \\
    MCP_API_KEY=your-api-key \\
    python3 scripts/test_mcp_integration.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent
LOGGER_SCRIPT = PROJECT_ROOT / "scripts" / "run_logger.py"
ANALYTICS_SCRIPT = PROJECT_ROOT / "scripts" / "run_analytics.py"

# Mode + remote config (read once at import time)
TEST_MODE = os.getenv("MCP_TEST_MODE", "stdio").lower()
API_BASE_URL = os.getenv("ATHLETE_API_BASE_URL", "http://localhost:8000").rstrip("/")
MCP_API_KEY = os.getenv("MCP_API_KEY")

# Terminal colors for output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"
BOLD = "\033[1m"


def pass_msg(label: str, detail: str = "") -> None:
    print(f"  {GREEN}[PASS]{RESET} {label}" + (f" — {detail}" if detail else ""))


def fail_msg(label: str, detail: str = "") -> None:
    print(f"  {RED}[FAIL]{RESET} {label}" + (f" — {detail}" if detail else ""))


def info(label: str) -> None:
    print(f"  {BLUE}[INFO]{RESET} {label}")


def section(title: str) -> None:
    print(f"\n{BOLD}{YELLOW}=== {title} ==={RESET}")


class MCPClient:
    """Minimal MCP client that speaks JSON-RPC over a subprocess's stdio."""

    def __init__(self, script_path: Path):
        self.script_path = script_path
        self.process: asyncio.subprocess.Process | None = None
        self._next_id = 1

    async def start(self) -> None:
        env = os.environ.copy()
        env.setdefault("ATHLETE_API_BASE_URL", "http://localhost:8000")
        env.setdefault("LOG_LEVEL", "WARNING")
        self.process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(self.script_path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

    async def stop(self) -> None:
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=3)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()

    async def _send(self, message: dict) -> None:
        if not self.process or not self.process.stdin:
            raise RuntimeError("Process not started")
        data = json.dumps(message) + "\n"
        self.process.stdin.write(data.encode())
        await self.process.stdin.drain()

    async def _recv(self) -> dict:
        if not self.process or not self.process.stdout:
            raise RuntimeError("Process not started")
        line = await asyncio.wait_for(self.process.stdout.readline(), timeout=10.0)
        if not line:
            stderr = b""
            if self.process.stderr:
                try:
                    stderr = await asyncio.wait_for(self.process.stderr.read(2000), timeout=1.0)
                except asyncio.TimeoutError:
                    pass
            raise RuntimeError(
                f"Server closed stdout. Stderr: {stderr.decode(errors='replace')}"
            )
        return json.loads(line.decode())

    async def request(self, method: str, params: dict | None = None) -> dict:
        msg_id = self._next_id
        self._next_id += 1
        msg = {"jsonrpc": "2.0", "id": msg_id, "method": method}
        if params is not None:
            msg["params"] = params
        await self._send(msg)
        return await self._recv()

    async def notify(self, method: str, params: dict | None = None) -> None:
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        await self._send(msg)

    async def initialize(self) -> dict:
        result = await self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"},
            },
        )
        await self.notify("notifications/initialized")
        return result

    async def list_tools(self) -> list[dict]:
        resp = await self.request("tools/list")
        return resp.get("result", {}).get("tools", [])

    async def call_tool(self, name: str, arguments: dict) -> dict:
        resp = await self.request(
            "tools/call", {"name": name, "arguments": arguments}
        )
        return resp.get("result", {})


class HTTPMCPClient:
    """Speaks JSON-RPC over an MCP streamable-http endpoint.

    Same surface as MCPClient (initialize/list_tools/call_tool) so the test
    bodies don't need to change between modes.
    """

    def __init__(self, mount_path: str):
        # mount_path is "/mcp/logger" or "/mcp/analytics" — the streamable_http
        # endpoint inside that mount lives at "{mount}/mcp"
        self.endpoint = f"{API_BASE_URL}{mount_path}/mcp"
        self._next_id = 1
        self._client = None
        self.label = mount_path

    async def start(self) -> None:
        import httpx

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if MCP_API_KEY:
            headers["Authorization"] = f"Bearer {MCP_API_KEY}"
        self._client = httpx.AsyncClient(timeout=30.0, headers=headers)

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _post(self, payload: dict) -> dict:
        if self._client is None:
            raise RuntimeError("Client not started")
        resp = await self._client.post(self.endpoint, json=payload)
        if resp.status_code == 401:
            raise RuntimeError(
                f"401 Unauthorized — check MCP_API_KEY env var. Body: {resp.text[:200]}"
            )
        resp.raise_for_status()
        return resp.json()

    async def request(self, method: str, params: dict | None = None) -> dict:
        msg_id = self._next_id
        self._next_id += 1
        msg = {"jsonrpc": "2.0", "id": msg_id, "method": method}
        if params is not None:
            msg["params"] = params
        return await self._post(msg)

    async def initialize(self) -> dict:
        # Stateless mode: no session id needed, no notifications/initialized
        # follow-up required to start using tools.
        return await self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"},
            },
        )

    async def list_tools(self) -> list[dict]:
        resp = await self.request("tools/list")
        return resp.get("result", {}).get("tools", [])

    async def call_tool(self, name: str, arguments: dict) -> dict:
        resp = await self.request(
            "tools/call", {"name": name, "arguments": arguments}
        )
        return resp.get("result", {})


def extract_text(call_result: dict) -> str:
    """Extract the text content from a tools/call response."""
    content = call_result.get("content", [])
    if content and isinstance(content, list):
        for item in content:
            if item.get("type") == "text":
                return item.get("text", "")
    return json.dumps(call_result)


async def test_logger_server() -> bool:
    section("LOGGER SERVER TEST")
    if TEST_MODE == "http":
        client = HTTPMCPClient("/mcp/logger")
        all_passed = True
        info(f"HTTP mode → {client.endpoint}")
    else:
        client = MCPClient(LOGGER_SCRIPT)
        all_passed = True
        info(f"Starting subprocess: {LOGGER_SCRIPT.name}")
    try:
        await client.start()

        # Step 1: Initialize
        try:
            init_result = await client.initialize()
            server_info = init_result.get("result", {}).get("serverInfo", {})
            pass_msg("initialize", f"server: {server_info.get('name', 'unknown')}")
        except Exception as e:
            fail_msg("initialize", str(e))
            return False

        # Step 2: tools/list
        try:
            tools = await client.list_tools()
            if len(tools) >= 10:
                pass_msg("tools/list", f"{len(tools)} tools")
                for t in tools:
                    desc = t.get("description", "")[:60].replace("\n", " ")
                    print(f"        - {t['name']}: {desc}...")
            else:
                fail_msg("tools/list", f"expected >=10 tools, got {len(tools)}")
                all_passed = False
        except Exception as e:
            fail_msg("tools/list", str(e))
            return False

        # Step 3: Call tool_log_set
        try:
            result = await client.call_tool(
                "tool_log_set",
                {"exercise": "pull_up", "reps": 8, "added_weight_kg": 5},
            )
            text = extract_text(result)
            parsed = json.loads(text)
            if parsed.get("success") and parsed.get("message"):
                pass_msg("tool_log_set", parsed["message"])
            else:
                fail_msg("tool_log_set", text[:200])
                all_passed = False
        except Exception as e:
            fail_msg("tool_log_set", str(e))
            all_passed = False

        # Step 4: Call tool_get_today
        try:
            result = await client.call_tool("tool_get_today", {})
            text = extract_text(result)
            parsed = json.loads(text)
            if parsed.get("success") and parsed.get("message"):
                pass_msg("tool_get_today", parsed["message"])
            else:
                fail_msg("tool_get_today", text[:200])
                all_passed = False
        except Exception as e:
            fail_msg("tool_get_today", str(e))
            all_passed = False

    finally:
        await client.stop()

    return all_passed


async def test_analytics_server() -> bool:
    section("ANALYTICS SERVER TEST")
    if TEST_MODE == "http":
        client = HTTPMCPClient("/mcp/analytics")
        all_passed = True
        info(f"HTTP mode → {client.endpoint}")
    else:
        client = MCPClient(ANALYTICS_SCRIPT)
        all_passed = True
        info(f"Starting subprocess: {ANALYTICS_SCRIPT.name}")
    try:
        await client.start()

        # Step 1: Initialize
        try:
            init_result = await client.initialize()
            server_info = init_result.get("result", {}).get("serverInfo", {})
            pass_msg("initialize", f"server: {server_info.get('name', 'unknown')}")
        except Exception as e:
            fail_msg("initialize", str(e))
            return False

        # Step 2: tools/list
        try:
            tools = await client.list_tools()
            if len(tools) >= 8:
                pass_msg("tools/list", f"{len(tools)} tools")
                for t in tools:
                    desc = t.get("description", "")[:60].replace("\n", " ")
                    print(f"        - {t['name']}: {desc}...")
            else:
                fail_msg("tools/list", f"expected >=8 tools, got {len(tools)}")
                all_passed = False
        except Exception as e:
            fail_msg("tools/list", str(e))
            return False

        # Step 3: Call tool_get_prs
        try:
            result = await client.call_tool("tool_get_prs", {})
            text = extract_text(result)
            parsed = json.loads(text)
            if parsed.get("success") and parsed.get("message"):
                pass_msg("tool_get_prs", parsed["message"])
            else:
                fail_msg("tool_get_prs", text[:200])
                all_passed = False
        except Exception as e:
            fail_msg("tool_get_prs", str(e))
            all_passed = False

        # Step 4: Call tool_weekly_summary
        try:
            result = await client.call_tool("tool_weekly_summary", {})
            text = extract_text(result)
            parsed = json.loads(text)
            if parsed.get("success") and parsed.get("message"):
                pass_msg("tool_weekly_summary", parsed["message"])
            else:
                fail_msg("tool_weekly_summary", text[:200])
                all_passed = False
        except Exception as e:
            fail_msg("tool_weekly_summary", str(e))
            all_passed = False

    finally:
        await client.stop()

    return all_passed


async def check_api_running() -> bool:
    """Verify the FastAPI server is reachable. Honors API_BASE_URL."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{API_BASE_URL}/health")
            return resp.status_code == 200
    except Exception:
        return False


async def main() -> int:
    print(f"{BOLD}MCP Integration Test{RESET}")
    print(f"Mode: {TEST_MODE}")
    print(f"API:  {API_BASE_URL}")
    if TEST_MODE == "http":
        print(f"Auth: {'Bearer ' + MCP_API_KEY[:8] + '...' if MCP_API_KEY else 'NONE (will fail if server requires auth)'}")
    print()

    section("PREFLIGHT")
    if not await check_api_running():
        fail_msg(
            f"API at {API_BASE_URL}",
            "not reachable. Start it locally or set ATHLETE_API_BASE_URL.",
        )
        return 1
    pass_msg(f"API at {API_BASE_URL}")

    if TEST_MODE == "http" and not MCP_API_KEY:
        fail_msg(
            "MCP_API_KEY not set",
            "HTTP mode against a deployed server needs the bearer token.",
        )
        return 1

    logger_ok = await test_logger_server()
    analytics_ok = await test_analytics_server()

    section("RESULT")
    if logger_ok and analytics_ok:
        print(f"  {GREEN}{BOLD}ALL TESTS PASSED{RESET}")
        print(f"  Both MCP servers are ready for Claude Desktop.")
        return 0
    else:
        print(f"  {RED}{BOLD}SOME TESTS FAILED{RESET}")
        if not logger_ok:
            print(f"  - Logger server failed")
        if not analytics_ok:
            print(f"  - Analytics server failed")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
