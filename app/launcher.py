"""Open only the CURRENT Studio instance from THIS Windows workspace."""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
import webbrowser

from .studio_identity import server_identity

URL = "http://127.0.0.1:8765"
IDENTITY_URL = URL + "/api/studio/identity"


def instance_released() -> bool:
    """A closed listener alone does not prove the previous server exited."""
    from .config import ROOT
    from .jobs import BusyError, InstanceLock
    path = ROOT / "data" / ".server.lock"
    if not path.exists():
        return True
    try:
        lock = InstanceLock(path)
    except (BusyError, OSError):
        return False
    lock.close()
    return True


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
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if studio_available():
            webbrowser.open(studio_url())
            return
        time.sleep(0.5)
    message = "Studio is not ready after 30 seconds. Check logs/LATEST.txt and server errors."
    import logging
    logging.getLogger("app.launcher").error(message,
        extra={"action": "startup_timeout", "status": "timeout"})
    print("[ERROR] " + message, flush=True)


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
    if not instance_released():
        print("[ERROR] Previous KADR Studio still holds its instance lock. "
              "Wait for shutdown or press Ctrl+C in its original console.", flush=True)
        raise SystemExit(2)
    print("Starting current KADR Studio on port 8765.", flush=True)
    threading.Thread(target=open_when_ready, daemon=True).start()
    from .server import main as serve
    try:
        serve()
    except Exception:
        logger.exception("Studio startup failed; inspect this diagnostic session",
                         extra={"action": "startup_failed", "status": "failed"})
        raise
    except SystemExit as error:
        if error.code not in (None, 0):
            logger.exception("Studio server exited before a normal shutdown",
                             extra={"action": "startup_failed", "status": "failed"})
        raise


def stop_studio() -> int:
    """Request idle-only shutdown of the verified workspace; never kill a PID."""
    from .config import setup_environment
    from .run_logging import configure_logging, scrub
    import logging
    setup_environment()
    configure_logging("studio")
    logger = logging.getLogger("app.launcher")
    status = studio_status()
    if status == "missing":
        if not instance_released():
            print("[ERROR] KADR listener is closed, but the previous server is still stopping. "
                  "Press Ctrl+C in its original console.", flush=True)
            return 2
        print("KADR Studio is already stopped.", flush=True)
        return 0
    if status != "current":
        print("[ERROR] Port 8765 belongs to another or outdated server. Stop it in its original console.",
              flush=True)
        return 2
    request = urllib.request.Request(URL + "/api/studio/shutdown",
        data=json.dumps({"identity": server_identity()}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=5) as response:
            if response.status != 202:
                raise ValueError("Unexpected shutdown response")
    except urllib.error.HTTPError as error:
        detail = "Shutdown refused. Wait for processing/export to finish, or use its Cancel button."
        try:
            message = json.loads(error.read(4096)).get("detail")
            if isinstance(message, str):
                detail = scrub(message)
        except (ValueError, AttributeError, OSError):
            pass
        logger.warning("Studio shutdown refused", extra={"action": "shutdown_refused", "status": error.code})
        print("[ERROR] " + detail, flush=True)
        return 2
    except (OSError, ValueError):
        logger.exception("Studio shutdown request failed", extra={"action": "shutdown_failed"})
        print("[ERROR] Could not request shutdown. Check logs/LATEST.txt.", flush=True)
        return 2
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if studio_status() == "missing" and instance_released():
            logger.info("Studio stopped", extra={"action": "shutdown_complete", "status": "stopped"})
            print("KADR Studio stopped. Saved projects and outputs remain available.", flush=True)
            return 0
        time.sleep(0.25)
    logger.error("Studio shutdown timed out", extra={"action": "shutdown_timeout", "status": "timeout"})
    print("[ERROR] Server has not stopped after 15 seconds. Check logs or use Ctrl+C in its console.", flush=True)
    return 2


def cli() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Start, reuse or stop this workspace's KADR Studio.")
    parser.add_argument("--stop", action="store_true", help="Stop only the verified idle Studio server")
    args = parser.parse_args()
    if args.stop:
        raise SystemExit(stop_studio())
    main()


if __name__ == "__main__":
    cli()
