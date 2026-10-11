"""An identity handshake so launchers never silently reuse an old local server.

Signatures are based on local repository files, not a synthetic job or demo.
The backend signature is captured at import time: a running Python process must
not claim to have adopted backend code that changed on disk afterwards.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_BACKEND = ("app/server.py", "app/launcher.py", "app/studio_identity.py")
_UI = ("frontend/dist/studio-edition.html", "frontend/dist/studio-live-bridge.js",
       "frontend/dist/studio-edition-app.js", "frontend/dist/studio-edition.css")


def _fingerprint(paths: tuple[str, ...]) -> str | None:
    digest = hashlib.sha256()
    for name in paths:
        path = ROOT / name
        if not path.is_file():
            return None
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:20]


def backend_fingerprint() -> str | None:
    if not all((ROOT / name).is_file() for name in _BACKEND):
        return None
    # Jobs, workers and analysis modules are imported lazily. A changed one
    # must invalidate reuse just like a changed HTTP entry point.
    paths = tuple(sorted(path.relative_to(ROOT).as_posix()
                         for path in (ROOT / 'app').glob('*.py')))
    return _fingerprint(paths)


def ui_fingerprint() -> str | None:
    return _fingerprint(_UI)


# Never refresh this at request time: it belongs to the *running* Python code.
RUNNING_BACKEND_FINGERPRINT = backend_fingerprint()


def server_identity() -> dict:
    return {
        "application": "kadr-studio",
        "interface": "studio-edition",
        "workspace": hashlib.sha256(str(ROOT.resolve()).casefold().encode("utf-8")).hexdigest()[:20],
        "backend": RUNNING_BACKEND_FINGERPRINT,
        "ui": ui_fingerprint(),
    }
