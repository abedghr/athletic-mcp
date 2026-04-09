"""Start the MCP analytics server (stdio transport)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from athlete_mcp.servers.analytics_server import main

if __name__ == "__main__":
    main()
