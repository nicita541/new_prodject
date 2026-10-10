"""Open only the CURRENT Studio instance from THIS Windows workspace."""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request
import webbrowser

from .studio_identity import server_identity

URL = "http://127.0.0.1:8765"
IDENTITY_URL = URL + "/api/studio/identity"


def port_occupied() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8765), timeout=0.5):
            return True
    except OSError:
        return False


def studio_status() -> str:
    """Return 'current', 'occupied' (old/different app), or 'missing'.

    /api/health is NOT sufficient: old Studio versions also return it.
    """
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(IDENTITY_URL, timeout=1) as response:
            remote = json.load(response)
        expected = server_identity()
        if (isinstance(remote, dict) and expected["ui"] is not None and
                all(remote.get(k) == expected[k] for k in
                    ("application", "interface", "workspace", "backend", "ui"))):
            return "current"
        return "occupied"
    except (OSError, ValueError, AttributeError, TypeError):
        return "occupied" if port_occupied() else "missing"


def studio_available() -> bool:
    return studio_status() == "current"


def studio_url() -> str:
    # A versioned URL also avoids a cached previous browser page.
    suffix = server_identity()["ui"] or "missing"
    return URL + "/studio-edition.html?v=" + suffix


def open_when_ready() -> None:
    for _ in range(60):
        if studio_available():
            webbrowser.open(studio_url())
            return
        time.sleep(0.5)
    print("[ERROR] Studio is not ready after 30 seconds. Check server errors.", flush=True)


def main() -> None:
    from .config import setup_environment
    setup_environment()
    from .run_logging import configure_logging
    from .config import ROOT
    import logging
    logs = configure_logging("studio")
    logger = logging.getLogger("app.launcher")
    logger.info("Launcher check, logs=%s", logs.relative_to(ROOT))
    status = studio_status()
    logger.info("Studio port status: %s", status, extra={"action": "port_check", "status": status})
    if status == "current":
        print("Reusing current KADR Studio on port 8765.", flush=True)
        webbrowser.open(studio_url())
        return
    if status == "occupied":
        print(
            "[ERROR] Port 8765 is occupied by an OLD KADR Studio, another "
            "worktree, or another application.\n"
            "This launcher will NOT open it as though it were the new Studio.\n"
            "Close the OLD server window with Ctrl+C after any running "
            "render/analysis has finished, then launch KADR again.\n"
            "If no console is visible, inspect the listener in PowerShell:\n"
            "Get-NetTCPConnection -LocalPort 8765 -State Listen | "
            "Select-Object OwningProcess",
            flush=True,
        )
        logger.error("Port occupied by another process; refusing to open an unrelated server",
                     extra={"action": "startup_refused", "status": "occupied"})
        raise SystemExit(2)
    print("Starting current KADR Studio on port 8765.", flush=True)
    threading.Thread(target=open_when_ready, daemon=True).start()
    from .server import main as serve
    serve()


if __name__ == "__main__":
    main()
