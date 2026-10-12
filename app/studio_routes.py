"""Studio static assets and screen links; no job, model or persistence logic."""
from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse


def create_studio_router(root: Path) -> APIRouter:
    router = APIRouter()
    dist_dir = root / "frontend" / "dist"
    # Studio is the sole interface. Its static builder copies these assets.
    studio_html = dist_dir / "studio-edition.html"
    studio_bridge = dist_dir / "studio-live-bridge.js"

    assets = {
        'studio-live-bridge.js': ('text/javascript', 'no-cache'),
        'studio-edition-app.js': ('text/javascript', 'no-store'),
        'studio-edition.css': ('text/css', 'no-store'),
        'studio-edition.html': ('text/html', 'no-cache'),
        'favicon.svg': ('image/svg+xml', 'no-cache'),
    }

    def studio_asset(request: Request):
        filename = request.url.path.removeprefix('/')
        media_type, cache_control = assets[filename]
        target = dist_dir / filename
        if not target.is_file():
            raise HTTPException(503, "Studio Edition не собрана. Выполните npm run build в frontend.")
        return FileResponse(target, media_type=media_type,
                            headers={'Cache-Control': cache_control})

    for filename in assets:
        router.add_api_route('/' + filename, studio_asset, methods=['GET', 'HEAD'],
                             name='studio_' + filename, include_in_schema=False)

    @router.api_route("/{full_path:path}", methods=["GET", "HEAD"])
    def index(full_path: str):
        if full_path.startswith(("api/", "assets/", "static/")):
            raise HTTPException(404)
        if full_path in {"legacy", "legacy/", "react-debug", "studio-edition-reference.html"}:
            raise HTTPException(404, "Этот интерфейс удалён; используйте KADR Studio")
        if not studio_html.is_file() or not studio_bridge.is_file():
            raise HTTPException(503, "Studio Edition не собрана. Выполните npm run build в frontend.")

        if full_path in {"", "projects"}:
            return FileResponse(studio_html, media_type="text/html",
                                headers={"Cache-Control": "no-cache"})

        screen = None
        ids = {}
        if full_path == "trash":
            screen = "trash"
        elif full_path == "studio":
            screen = "finishing"
        elif full_path == "api":
            screen = "api"
        else:
            project = re.fullmatch(r"project/([^/]+)", full_path)
            episode = re.fullmatch(r"episode/([^/]+)/(edit|review|finishing)(?:/([^/]+))?", full_path)
            if project:
                screen = "episodes"
                ids["project"] = project.group(1)
            elif episode:
                screen = {"edit": "editor", "review": "review",
                          "finishing": "finishing"}[episode.group(2)]
                ids["episode"] = episode.group(1)
                if episode.group(3):
                    ids["job"] = episode.group(3)
        if screen is None:
            raise HTTPException(404, "Экран не найден")
        return RedirectResponse("/studio-edition.html?" + urlencode({"screen": screen, **ids}),
                                status_code=307)
    return router
