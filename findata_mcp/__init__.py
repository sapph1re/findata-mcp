"""FinData MCP — Financial data for AI agents via hosted backend with x402 payments."""


def main() -> None:
    """Start the FinData MCP thin client (stdio transport)."""
    from findata_mcp.server import mcp
    mcp.run()
