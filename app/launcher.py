"""Double-click startup: reuse the studio, open the page after readiness."""
from __future__ import annotations

import json
import threading
import time
import urllib.request
import webbrowser

URL = 'http://127.0.0.1:8765'


def studio_available() -> bool:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(URL + '/api/health', timeout=1) as response:
            state = json.load(response)
        return isinstance(state.get('ready'), bool) and isinstance(state.get('missing'), list)
    except (OSError, ValueError, AttributeError):
        return False


def open_when_ready():
    for _ in range(60):
        if studio_available():
            webbrowser.open(URL)
            return
        time.sleep(0.5)
    print('Страница: ' + URL, flush=True)


def main():
    from .config import setup_environment
    setup_environment()
    if studio_available():
        webbrowser.open(URL)
        return
    threading.Thread(target=open_when_ready, daemon=True).start()
    from .server import main as serve
    serve()


if __name__ == '__main__':
    main()
