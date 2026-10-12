"""Gated child: parent assigns Windows Job Object before any grandchildren start."""
from __future__ import annotations

import argparse
import os
import subprocess
import time
from pathlib import Path

from app.json_store import read_json
from app.mcp_contract import resolve_under
from devtools.mcp_tasks import command


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', required=True)
    args = parser.parse_args()
    directory = resolve_under(root / 'temp/mcp-tasks', args.directory)
    deadline = time.monotonic() + 20
    while not (directory / '.start').is_file():
        if time.monotonic() >= deadline: return 2
        time.sleep(.02)
    temp = directory / 'temp'
    temp.mkdir()
    env = {**os.environ, 'TEMP': str(temp), 'TMP': str(temp), 'TMPDIR': str(temp),
        'PYTHONPYCACHEPREFIX': str(root / 'temp/pycache'), 'PYTHONIOENCODING': 'utf-8',
        'PIP_CACHE_DIR': str(root / 'cache/pip'), 'npm_config_cache': str(root / 'cache/npm')}
    specification = read_json(directory / 'specification.json')
    return subprocess.call(command(root, specification), cwd=root, env=env,
        stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)


if __name__ == '__main__':
    raise SystemExit(main())
