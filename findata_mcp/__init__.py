"""FinData MCP — Financial data server for AI agents.

Entry point for PyPI / uvx installation:
  uvx findata-mcp
  smithery install findata-mcp
"""

import os
import sys


def main() -> None:
    """Start the FinData MCP server (stdio transport for Claude Desktop / MCP clients)."""
    # When installed via pip/uvx, bundled sources live alongside this __init__.py
    pkg_dir = os.path.dirname(__file__)
    if pkg_dir not in sys.path:
        sys.path.insert(0, pkg_dir)

    from server import mcp  # noqa: PLC0415
    mcp.run()
