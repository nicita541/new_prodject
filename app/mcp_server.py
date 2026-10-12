"""Product MCP entry point; does not import development tools or start Studio."""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path


def workspace_environment(root):
    # Only configure environment; read-only tools must not mkdir on startup.
    for key in ('TEMP', 'TMP', 'TMPDIR'): os.environ[key] = str(root / 'temp')
    os.environ['PYTHONPYCACHEPREFIX'] = str(root / 'temp/pycache')
    os.environ['PIP_CACHE_DIR'] = str(root / 'cache/pip')
    os.environ['npm_config_cache'] = str(root / 'cache/npm')


def main():
    root = Path(__file__).resolve().parents[1]
    workspace_environment(root)
    parser = argparse.ArgumentParser(description='KADR product MCP over stdio; Studio must already be running')
    parser.add_argument('--backend', default='http://127.0.0.1:8765')
    args = parser.parse_args()
    from app.mcp_product import Product
    from app.mcp_runtime import run
    asyncio.run(run(Product(root, args.backend), 'kadr'))


if __name__ == '__main__': main()
