"""Explicit developer-only MCP connection, separate from the product entry point."""
from __future__ import annotations

import asyncio
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    from app.mcp_server import workspace_environment
    workspace_environment(root)
    from app.mcp_runtime import run
    from devtools.mcp_dev import Development
    asyncio.run(run(Development(root), 'kadr-dev'))


if __name__ == '__main__': main()
