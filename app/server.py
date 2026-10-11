"""Loopback-only HTTP API and static UI; no model downloads at runtime."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlsplit, urlencode

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from app import config
from app.studio_identity import server_identity
from app.jobs import BusyError, JobManager, contained, read_json
from app.quality import debug_timeline, summarize_plan
from app.part_context import with_context
from app.music import list_tracks, load_settings, save_settings

MAX_UPLOAD = 20 * 1024 ** 3
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}
MULTIPART_OVERHEAD = 64 * 1024


class BrowserDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["ui_action", "ui_error", "unhandled_rejection"]
    action: str = Field(default="", max_length=80)
    message: str = Field(default="", max_length=500)
    line: int = Field(default=0, ge=0, le=1000000)


class StudioShutdown(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    identity: dict[str, str | None]


class UploadTooLarge(HTTPException):
    def __init__(self):
        super().__init__(413, "Серия слишком большая (предел 20 ГБ)")


class UploadLimitMiddleware:
    """Bound the body before multipart parsing can spool it to disk."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope["type"] != "http" or scope.get("method") != "POST" or
                scope.get("path") not in {"/api/import", "/api/music/import"}):
            return await self.app(scope, receive, send)
        music_upload = scope.get("path") == "/api/music/import"
        # Reject an oversized upload before Starlette spools its multipart body.
        limit = (35 * 1024 * 1024 if music_upload else MAX_UPLOAD) + MULTIPART_OVERHEAD
        error_text = "Музыкальный файл больше 35 МБ" if music_upload else "Серия слишком большая (предел 20 ГБ)"
        rejection = JSONResponse({"detail": error_text}, 413)
        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length" and value.isdigit() and int(value) > limit:
                return await rejection(scope, receive, send)
        received = 0
        async def bounded_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # Starlette closes partial multipart temporary files when
                    # its input stream raises; never deliver this block to it.
                    raise UploadTooLarge()
            return message
        try:
            await self.app(scope, bounded_receive, send)
        except UploadTooLarge:
            await rejection(scope, receive, send)


class CreateJob(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    analysis_provider: Literal["local", "deepseek", "hybrid", "deepseek_plan", "local_flash_story", "local_fast_story", "local_flash_story_budgeted", "antigravity_manual"] = "local"
    layout: Literal["portrait", "cinema"] = "portrait"
    caption_style: Literal["classic", "accent"] = "classic"


class ManualAnalysisMode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["local", "antigravity_manual"]


class RecoverDeepseek(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accept_reserved_costs: Literal[True]


class SaveVideos(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str | None = None
    all: bool = False
    destination: str | None = None


class CreateProject(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=200)


class CreateEpisode(BaseModel):
    model_config = ConfigDict(extra='forbid')
    number: int | None = Field(default=None, ge=1, le=9999, strict=True)


class EpisodeSettings(CreateJob):
    pass


class MusicSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool
    volume: float = Field(ge=0, le=1)
    track: str | None = None
    mode: Literal["random_per_part", "single", "per_part"] = "random_per_part"
    part_tracks: dict[str, str | None] | None = None


def safe_filename(name: str | None) -> str:
    if not name or len(name) > 1024 or "/" in name or "\\" in name or ":" in name:
        raise ValueError("Выберите файл с обычным именем, без пути")
    if any(ord(character) < 32 for character in name) or name.endswith((".", " ")):
        raise ValueError("Недопустимое имя файла")
    if Path(name).suffix.lower() not in {".mp4", ".mkv"}:
        raise ValueError("Поддерживаются только MP4 и MKV")
    # Import directory is a UUID, but also avoid Windows reserved names and
    # characters. Preserve the full original name in source metadata.
    stem = re.sub(r'[<>"|?*]', "_", Path(name).stem).strip(" .")[:100] or "episode"
    if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", stem):
        stem = "episode_" + stem
    return stem + Path(name).suffix.lower()


def choose_download_directory() -> str | None:
    """Use a native folder chooser, PowerShell dialog, or env fallback; callers may also supply destination directly."""
    env_dest = os.environ.get("AUTOSHORT_DOWNLOAD_DIR")
    if env_dest and Path(env_dest).is_dir():
        return str(Path(env_dest).resolve())

    # 1. On Windows, use native FolderBrowserDialog via PowerShell (works cleanly without Tcl/Tk)
    if os.name == "nt":
        try:
            ps_script = (
                "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; "
                "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
                "$d.Description = 'Куда сохранить видео?'; "
                "$d.ShowNewFolderButton = $true; "
                "if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { "
                "  Write-Output $d.SelectedPath "
                "}"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                capture_output=True, text=True, timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            )
            selected = result.stdout.strip()
            if selected and Path(selected).is_dir():
                return str(Path(selected).resolve())
            if result.returncode == 0 and not selected:
                # User clicked Cancel in dialog
                return None
        except Exception:
            pass

    # 2. Try Tkinter fallback if available
    try:
        import tkinter
        from tkinter import filedialog

        root = tkinter.Tk()
        try:
            root.withdraw()
            root.attributes("-topmost", True)
            root.update()
            selected = filedialog.askdirectory(parent=root, title="Куда сохранить видео?", mustexist=True)
            if selected:
                return str(Path(selected).resolve())
            return None
        finally:
            try:
                root.destroy()
            except Exception:
                pass
    except Exception:
        pass

    # The caller must explicitly choose where exports go. Never copy to an
    # unrelated default directory when both native file pickers are broken.
    raise RuntimeError("Интерактивный выбор папки недоступен")


def validate_media(path: Path) -> None:
    if not config.FFPROBE.is_file():
        raise RuntimeError("FFprobe не установлен. Запустите setup.bat.")
    try:
        result = subprocess.run(
            [str(config.FFPROBE), "-v", "error", "-protocol_whitelist", "file,pipe", "-format_whitelist", "mov,matroska,webm", "-show_streams", "-show_format", "-of", "json", str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, check=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        probe = json.loads(result.stdout.decode("utf-8"))
        streams = probe.get("streams", [])
        duration = float(probe.get("format", {}).get("duration", 0))
        if not any(item.get("codec_type") == "video" for item in streams):
            raise ValueError("В файле нет видеодорожки")
        if not any(item.get("codec_type") == "audio" for item in streams):
            raise ValueError("В серии нет звуковой дорожки")
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("Не удалось определить длительность серии")
    except (subprocess.SubprocessError, json.JSONDecodeError, UnicodeError) as error:
        raise ValueError("Файл повреждён или не является видео MP4/MKV") from error


def safe_message(error: Exception, manager: JobManager) -> str:
    # Exceptions may contain source paths; public clients only see opaque IDs.
    text = str(error)
    text = text.replace(str(manager.root), "[папка проекта]")
    return text


def public_job(job: dict, manager: JobManager | None = None) -> dict:
    result = dict(job)
    result.setdefault("analysis_provider", "local")
    identifier = job["id"]
    if manager:
        from .job_progress import stage_progress
        result['stage_progress'] = stage_progress(job, manager.job_dir(identifier))
    outputs = job.get("outputs", []) if job["status"] == "completed" else []
    durations = {}
    if outputs and manager:
        plan_path = contained(manager.job_dir(identifier) / "plan.json", manager.jobs)
        saved_plan = read_json(plan_path, {})
        durations = {f"part_{part['index']:03}.mp4": part.get("duration")
                     for part in saved_plan.get("parts", []) if isinstance(part.get("index"), int)}
    result["files"] = [{"name": name, "url": f"/api/jobs/{identifier}/files/{name}",
                        "subtitle_url": f"/api/jobs/{identifier}/files/{Path(name).stem}.srt"
                        if f"{Path(name).stem}.srt" in outputs else None,
                        "duration": durations.get(name)}
                       for name in outputs if name.endswith(".mp4")]
    return result


def ranged_file(path: Path, request: Request, as_attachment: bool = False):
    """Single-range streaming with bounded reads and correct 416 responses."""
    length = path.stat().st_size
    start, end, status = 0, length - 1, 200
    range_header = request.headers.get("range")
    if range_header:
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
        if not match or not any(match.groups()) or length == 0:
            return JSONResponse({"detail": "Недопустимый диапазон"}, 416,
                                headers={"Content-Range": f"bytes */{length}", "Accept-Ranges": "bytes"})
        left, right = match.groups()
        if left:
            start = int(left)
            end = min(int(right), length - 1) if right else length - 1
        else:
            suffix = int(right)
            start = max(0, length - suffix)
            if suffix == 0:
                start = length
        if start >= length or end < start:
            return JSONResponse({"detail": "Диапазон за пределами файла"}, 416,
                                headers={"Content-Range": f"bytes */{length}", "Accept-Ranges": "bytes"})
        status = 206
    disposition = "attachment" if as_attachment else "inline"
    headers = {"Accept-Ranges": "bytes", "Content-Length": str(max(0, end - start + 1)),
               "Content-Disposition": f"{disposition}; filename*=UTF-8''" + quote(path.name, safe=""),
               "X-Content-Type-Options": "nosniff"}
    if status == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{length}"
    def chunks():
        with path.open("rb") as stream:
            stream.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                content = stream.read(min(1024 * 1024, remaining))
                if not content:
                    break
                yield content
                remaining -= len(content)
    return StreamingResponse(iter(()) if request.method == "HEAD" else chunks(), status_code=status,
                             media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                             headers=headers)


def create_app(manager: JobManager | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application):
        config.setup_environment()
        from .run_logging import configure_logging
        configure_logging("studio")
        logging.getLogger("app.server").info("Studio API startup",
            extra={"action": "server_start", "status": "running"})
        application.state.manager = manager or JobManager()
        try:
            from .library import Library
            application.state.library = Library(application.state.manager)
            yield
        finally:
            logging.getLogger("app.server").info("Studio API shutting down",
                extra={"action": "server_stop"})
            application.state.manager.close()
    application = FastAPI(title="Аниме → шортсы", lifespan=lifespan,
                          docs_url=None, redoc_url=None, openapi_url=None)
    application.state.download_picker_lock = threading.Lock()
    application.add_middleware(UploadLimitMiddleware)

    @application.get("/api/studio/identity")
    def studio_version():
        # Captured backend code + current UI assets; no user data exposed.
        return server_identity()

    @application.middleware("http")
    async def protect_loopback(request: Request, call_next):
        try:
            host = urlsplit("http://" + request.headers.get("host", ""))
            if host.hostname not in ALLOWED_HOSTS or host.username or host.password:
                raise ValueError()
            port = host.port or 80
        except ValueError:
            return JSONResponse({"detail": "Разрешён только локальный адрес"}, 403)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin:
                try:
                    parsed = urlsplit(origin)
                    if (parsed.scheme != "http" or parsed.hostname != host.hostname or
                            (parsed.port or 80) != port or parsed.username or parsed.password or
                            parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
                        raise ValueError()
                except ValueError:
                    return JSONResponse({"detail": "Запрос разрешён только из этого приложения"}, 403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Запрос с другого сайта запрещён"}, 403)
            if request.headers.get("content-type", "").split(";", 1)[0].lower() not in {
                "application/json", "multipart/form-data", ""}:
                return JSONResponse({"detail": "Недопустимый формат запроса"}, 415)
            current = getattr(request.app.state, "manager", None)
            if current is not None and current.shutdown_requested:
                return JSONResponse({"detail": "Приложение завершает работу"}, 409)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logging.getLogger("app.server").exception("Unexpected HTTP failure",
                extra={"action": "http_failure", "http_method": request.method,
                       "http_route": "unhandled", "http_status": 500})
            raise
        if request.url.path.startswith("/api/") and request.url.path != "/api/diagnostics/client":
            route = request.scope.get("route")
            template = getattr(route, "path", "unmatched")
            logging.getLogger("app.server").log(
                logging.WARNING if response.status_code >= 400 else logging.INFO,
                "HTTP %s %s -> %s", request.method, template, response.status_code,
                extra={"action": "http_request", "http_method": request.method,
                       "http_route": template, "http_status": response.status_code,
                       "elapsed_ms": round((time.perf_counter()-started)*1000, 2)})
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; media-src 'self'; "
            "style-src 'self' 'unsafe-inline'; script-src 'self'; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        )
        return response

    def get_manager(request: Request):
        return request.app.state.manager

    @application.post("/api/studio/shutdown", status_code=202)
    def shutdown_studio(request: Request, body: StudioShutdown):
        if body.identity != server_identity():
            raise HTTPException(409, "Запущен другой экземпляр KADR; остановка отклонена")
        callback = getattr(request.app.state, "shutdown_callback", None)
        if not callable(callback):
            raise HTTPException(409, "Этот запуск не поддерживает остановку через API; используйте Ctrl+C")
        current = get_manager(request)
        with current.mutex:
            if current.closed or current.shutdown_requested:
                raise HTTPException(409, "Приложение завершает работу")
            if current.active is not None or any(current.finishing_tasks.values()):
                raise HTTPException(409, "Дождитесь завершения экспорта или отмените обработку в интерфейсе")
            current.shutdown_requested = True
            try:
                callback()
            except Exception:
                current.shutdown_requested = False
                logging.getLogger("app.server").exception("Studio shutdown callback failed",
                    extra={"action": "shutdown_failed", "status": "failed"})
                raise HTTPException(500, "Не удалось запросить остановку приложения") from None
        logging.getLogger("app.server").info("Idle Studio shutdown requested",
            extra={"action": "shutdown_requested", "status": "stopping"})
        return {"status": "shutdown_requested"}

    @application.exception_handler(BusyError)
    async def busy_error(request: Request, error: BusyError):
        return JSONResponse({"detail": str(error)}, 409)

    @application.exception_handler(KeyError)
    async def missing_error(request: Request, error: KeyError):
        return JSONResponse({"detail": "Серия или задание не найдены"}, 404)

    @application.exception_handler(ValueError)
    async def invalid_error(request: Request, error: ValueError):
        return JSONResponse({"detail": safe_message(error, get_manager(request))}, 400)

    @application.post("/api/diagnostics/client", status_code=204)
    def client_diagnostics(body: BrowserDiagnostic):
        # Browser sends only coarse action labels and exception summaries:
        # never record input fields, request bodies, URL queries or credentials.
        from .run_logging import scrub
        logging.getLogger("app.browser").log(
            logging.WARNING if body.kind != "ui_action" else logging.INFO,
            "Browser %s: %s %s", body.kind, scrub(body.action), scrub(body.message),
            extra={"action": body.kind, "stage": "browser", "code": body.line})
        return None

    @application.get("/api/health")
    def health(request: Request):
        return {**config.readiness(), "busy": get_manager(request).busy()}

    @application.get("/api/sources")
    def sources(request: Request):
        return get_manager(request).list_sources()

    @application.get('/api/library')
    def library(request: Request):
        return request.app.state.library.snapshot()

    @application.delete('/api/projects/{identifier}')
    def delete_project(request: Request, identifier: str):
        return request.app.state.library.archive('project', identifier)

    @application.delete('/api/episodes/{identifier}')
    def delete_episode(request: Request, identifier: str):
        return request.app.state.library.archive('episode', identifier)

    @application.post('/api/projects/{identifier}/restore')
    def restore_project(request: Request, identifier: str):
        return request.app.state.library.restore('project', identifier)

    @application.post('/api/episodes/{identifier}/restore')
    def restore_episode(request: Request, identifier: str):
        return request.app.state.library.restore('episode', identifier)

    @application.post('/api/projects', status_code=201)
    def new_project(request: Request, body: CreateProject):
        return request.app.state.library.create_project(body.title)

    @application.post('/api/projects/{identifier}/episodes', status_code=201)
    def new_episode(request: Request, identifier: str, body: CreateEpisode):
        return request.app.state.library.create_episode(identifier, body.number)

    @application.put('/api/episodes/{identifier}/settings')
    def episode_settings(request: Request, identifier: str, body: EpisodeSettings):
        values = body.model_dump()
        source_id = values.pop('source_id')
        return request.app.state.library.save_episode(identifier, source_id, values)

    @application.post('/api/episodes/{identifier}/jobs', status_code=201)
    def episode_job(request: Request, identifier: str):
        if not config.readiness()['ready']:
            raise HTTPException(503, 'Сначала выполните локальную настройку проекта')
        return public_job(request.app.state.library.launch(identifier), get_manager(request))

    @application.get("/api/music")
    def music_settings():
        settings = load_settings()
        return {"enabled": settings["enabled"], "volume": settings["volume"],
                "fade_in": settings["fade_in"], "fade_out": settings["fade_out"],
                "track": settings["track"], "mode": settings.get("mode", "random_per_part"),
                "part_tracks": settings.get("part_tracks", {}),
                "tracks": [path.name for path in list_tracks(config.MUSIC)],
                "folder": str(config.MUSIC.resolve())}

    @application.put("/api/music")
    def save_music_settings(body: MusicSettings):
        settings = load_settings()
        track = (body.track or "").strip() or None
        saved = save_settings({
            **settings,
            "enabled": body.enabled,
            "volume": body.volume,
            "track": track,
            "mode": body.mode,
            "part_tracks": body.part_tracks or {},
        })
        return {"enabled": saved["enabled"], "volume": saved["volume"],
                "fade_in": saved["fade_in"], "fade_out": saved["fade_out"],
                "track": saved["track"], "mode": saved.get("mode", "random_per_part"),
                "part_tracks": saved.get("part_tracks", {}),
                "tracks": [path.name for path in list_tracks(config.MUSIC)]}

    @application.post("/api/music/open")
    def open_music_folder():
        target = config.MUSIC.resolve()
        target.mkdir(parents=True, exist_ok=True)
        errors = []
        try:
            # Use string command so cmd/explorer parses the path natively,
            # avoiding Popen list escaping issues and path resolution bugs.
            subprocess.Popen(f'explorer "{target}"')
            return {"opened": True, "path": str(target)}
        except Exception as error:
            errors.append(str(error))
        try:
            os.startfile(str(target))
            return {"opened": True, "path": str(target)}
        except Exception as error:
            errors.append(str(error))
        raise HTTPException(500, f"Не удалось открыть папку музыки: {'; '.join(errors)}")

    @application.get("/api/deepseek")
    def deepseek_status():
        try:
            from app.deepseek import public_status
            state = public_status()
            return {key: state[key] for key in ("configured", "budget_usd", "charged_ceiling_usd",
                                               "remaining_usd", "model")}
        except Exception:
            raise HTTPException(503, "Не удалось прочитать локальные настройки DeepSeek") from None

    @application.post("/api/deepseek/check")
    def deepseek_check():
        try:
            from app.deepseek import check_connection
            state = check_connection()
            return {"available": state["available"], "model": state["model"],
                    "vision_supported": state["vision_supported"],
                    "balance_infos": [{"currency": item["currency"], "total_balance": item["total_balance"]}
                                      for item in state["balance_infos"]]}
        except Exception:
            raise HTTPException(503, "Не удалось проверить соединение с DeepSeek") from None

    @application.get('/api/deepseek/balance')
    def provider_balance_status():
        return {'accounting_enabled': False}

    @application.post('/api/deepseek/balance')
    def provider_balance_refresh(request: Request, job_id: str | None = None, force: bool = False):
        if job_id is not None:
            get_manager(request).get(job_id)
        return {'accounting_enabled': False}

    @application.get('/api/deepseek/recovery')
    def deepseek_recovery_status():
        from .deepseek import recovery_status
        return recovery_status()

    @application.post('/api/deepseek/recovery')
    def deepseek_recovery(body: RecoverDeepseek):
        try:
            from .deepseek import acknowledge_reserved_requests
            return acknowledge_reserved_requests()
        except Exception:
            raise HTTPException(503, 'Восстановление не выполнено. Проверьте подключение и баланс.') from None

    @application.post("/api/import", status_code=201)
    async def import_source(request: Request, file: UploadFile = File(...)):
        current = get_manager(request)
        destination = None
        temporary = None
        try:
            # Multipart already knows the file byte count. Reject the small
            # envelope-tolerance excess before creating a second file copy.
            if file.size is not None and file.size > MAX_UPLOAD:
                raise HTTPException(413, "Серия слишком большая (предел 20 ГБ)")
            filename = safe_filename(file.filename)
            directory = current.imports / str(uuid.uuid4())
            directory.mkdir()
            temporary = directory / ".upload"
            destination = directory / filename
            size = 0
            with temporary.open("xb") as stream:
                while block := await file.read(1024 * 1024):
                    size += len(block)
                    if size > MAX_UPLOAD:
                        raise HTTPException(413, "Серия слишком большая (предел 20 ГБ)")
                    stream.write(block)
            if size == 0:
                raise ValueError("Выбран пустой файл")
            await asyncio.to_thread(validate_media, temporary)
            temporary.replace(destination)
            return current.register_import(destination, file.filename)
        except RuntimeError as error:
            raise HTTPException(503, safe_message(error, current)) from error
        except OSError as error:
            raise HTTPException(507, "Не удалось сохранить серию. Проверьте свободное место и доступ к папке.") from error
        finally:
            await file.close()
            if temporary:
                temporary.unlink(missing_ok=True)
            if destination and not destination.exists():
                destination.parent.rmdir()

    @application.post("/api/jobs", status_code=201)
    def create_job(request: Request, body: CreateJob):
        state = config.readiness()
        if body.analysis_provider == 'antigravity_manual':
            missing = [name for name in state['missing'] if name not in {
                'Qwen3.5-9B для сокращения истории', 'Визуальный проектор Qwen 9B'}]
            state = {'missing': missing, 'ready': not missing}
        if not state["ready"]:
            raise HTTPException(503, "Не установлены компоненты: " + ", ".join(state["missing"]))
        current = get_manager(request)
        return public_job(current.create(body.source_id, body.analysis_provider,
                                         body.layout, body.caption_style), current)

    @application.get("/api/jobs")
    def jobs(request: Request):
        current = get_manager(request)
        return [public_job(job, current) for job in current.list_jobs()]

    @application.get("/api/jobs/{identifier}")
    def job(request: Request, identifier: str):
        current = get_manager(request)
        return public_job(current.get(identifier), current)

    @application.delete("/api/jobs/{identifier}")
    def delete_job(request: Request, identifier: str):
        current = get_manager(request)
        return current.delete_job(identifier)

    @application.post("/api/jobs/prune")
    def prune_jobs(request: Request, max_jobs: int = 50, max_age_days: int | None = 30):
        current = get_manager(request)
        return current.prune_jobs(max_jobs=max_jobs, max_age_days=max_age_days)

    @application.get('/api/jobs/{identifier}/spending')
    def spending(request: Request, identifier: str):
        current = get_manager(request)
        current.get(identifier)
        from .deepseek import job_spending
        return job_spending(current.job_dir(identifier))

    @application.get("/api/jobs/{identifier}/tokens")
    def token_stats(request: Request, identifier: str):
        current = get_manager(request)
        current.get(identifier)
        from .token_usage import summary
        return summary(current.job_dir(identifier))

    @application.get('/api/jobs/{identifier}/antigravity')
    def manual_analysis(request: Request, identifier: str):
        current = get_manager(request)
        current.get(identifier)
        from .antigravity_exchange import snapshot
        return snapshot(current.job_dir(identifier))

    @application.post('/api/jobs/{identifier}/analysis-provider')
    def manual_analysis_mode(request: Request, identifier: str, body: ManualAnalysisMode):
        current = get_manager(request)
        from .antigravity_exchange import preserve_provider_checkpoints
        from .jobs import atomic_json, TERMINAL
        with current.mutex:
            current._assert_available()
            job = current.get(identifier)
            if job['status'] not in TERMINAL or job['status'] == 'completed':
                raise BusyError('Сначала остановите обработку; готовое задание менять нельзя')
            directory = current.job_dir(identifier)
            old = job.get('analysis_provider', 'local')
            preserve_provider_checkpoints(directory, old, body.provider)
            settings = read_json(directory / 'analysis-settings.json', {})
            atomic_json(directory / 'analysis-settings.json', {**settings, 'provider': body.provider})
            job['analysis_provider'] = body.provider
            atomic_json(directory / 'job.json', job)
            return public_job(job, current)

    @application.post('/api/jobs/{identifier}/antigravity/prepare')
    def prepare_manual_analysis(request: Request, identifier: str):
        current = get_manager(request)
        if current.get(identifier).get('analysis_provider') != 'antigravity_manual':
            raise ValueError('Выберите ручной режим Antigravity для этого задания')
        return public_job(current.retry(identifier), current)

    @application.post('/api/jobs/{identifier}/antigravity/open')
    def open_manual_analysis(request: Request, identifier: str):
        current = get_manager(request)
        current.get(identifier)
        directory = contained(current.job_dir(identifier) / 'antigravity', current.job_dir(identifier))
        directory.mkdir(exist_ok=True)
        if os.name == 'nt':
            subprocess.Popen(['explorer.exe', str(directory)])
        return {'opened': os.name == 'nt'}

    @application.post('/api/jobs/{identifier}/antigravity/{packet_id}/import')
    async def import_manual_analysis(request: Request, identifier: str, packet_id: str):
        current = get_manager(request)
        from .antigravity_exchange import import_result, MAX_RESULT_BYTES
        # Read a bounded stream rather than buffering an arbitrary request.
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_RESULT_BYTES:
                raise HTTPException(413, 'Результат больше 8 МБ')
        with current.mutex:
            current._assert_available()
            job = current.get(identifier)
            if job.get('analysis_provider') != 'antigravity_manual' or job['status'] == 'completed':
                raise ValueError('Импорт доступен для остановленного ручного задания')
            return import_result(current.job_dir(identifier), packet_id, bytes(body))

    @application.post("/api/jobs/{identifier}/cancel")
    def cancel(request: Request, identifier: str):
        current = get_manager(request)
        return public_job(current.cancel(identifier), current)

    @application.post('/api/jobs/{identifier}/reset-budget')
    def reset_budget(request: Request, identifier: str):
        return get_manager(request).reset_attempt_budget(identifier)

    @application.post("/api/jobs/{identifier}/retry")
    def retry(request: Request, identifier: str):
        state = config.readiness()
        if not state["ready"]:
            raise HTTPException(503, "Не установлены компоненты: " + ", ".join(state["missing"]))
        current = get_manager(request)
        return public_job(current.retry(identifier), current)

    @application.get("/api/jobs/{identifier}/plan")
    def plan(request: Request, identifier: str):
        current = get_manager(request)
        current.get(identifier)
        result = read_json(contained(current.job_dir(identifier) / "plan.json", current.jobs))
        if result is None:
            raise HTTPException(404, "Монтажный план ещё не готов")
        if isinstance(result, dict):
            # Derived, bounded diagnostics use the existing plan response and
            # never expose provider payloads or filesystem metadata.
            result = with_context(result)
            result["quality_summary"] = summarize_plan(result)
            result["debug_timeline"] = debug_timeline(result)
        return result

    @application.api_route('/api/jobs/{identifier}/source', methods=['GET', 'HEAD'])
    def original_source(request: Request, identifier: str):
        current = get_manager(request)
        current.get(identifier)
        record = read_json(current.job_dir(identifier) / 'source.json')
        if not record or not isinstance(record.get('path'), str):
            raise HTTPException(404, 'Исходная серия недоступна')
        path = contained(Path(record['path']), current.root)
        if not path.is_file() or path.suffix.lower() not in {'.mp4', '.mkv'}:
            raise HTTPException(404, 'Исходная серия недоступна')
        return ranged_file(path, request)

    @application.api_route("/api/jobs/{identifier}/files/{filename}", methods=["GET", "HEAD"])
    def output(request: Request, identifier: str, filename: str):
        current = get_manager(request)
        item = current.get(identifier)
        if (item["status"] != "completed" or filename not in item.get("outputs", []) or
                Path(filename).name != filename or "/" in filename or "\\" in filename or
                Path(filename).suffix not in {".mp4", ".srt"}):
            raise HTTPException(404, "Готовый файл не найден")
        directory = contained(current.job_dir(identifier) / "output", current.job_dir(identifier))
        path = contained(directory / filename, directory)
        if not path.is_file():
            raise HTTPException(404, "Готовый файл не найден")
        as_download = bool(request.query_params.get("download"))
        return ranged_file(path, request, as_attachment=as_download)

    @application.post("/api/jobs/{identifier}/open-folder")
    def open_job_folder(request: Request, identifier: str):
        current = get_manager(request)
        item = current.get(identifier)
        if item.get("status") != "completed":
            raise HTTPException(400, "Задание ещё не завершено")
        output_dir = contained(current.job_dir(identifier) / "output", current.job_dir(identifier))
        target = output_dir.resolve()
        if not target.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        try:
            if os.name == "nt":
                subprocess.Popen(f'explorer "{target}"')
            return {"opened": True, "path": str(target)}
        except Exception:
            return JSONResponse({"opened": False, "detail": "Не удалось открыть папку проводника"}, 500)

    @application.post("/api/jobs/{identifier}/save-videos")
    def save_videos(request: Request, identifier: str, body: SaveVideos):
        current = get_manager(request)
        item = current.get(identifier)
        if item["status"] != "completed":
            raise HTTPException(404, "Готовые видео не найдены")
        registered = item.get("outputs", [])
        mp4_names = [name for name in registered
                     if isinstance(name, str) and Path(name).name == name
                     and "/" not in name and "\\" not in name and Path(name).suffix.lower() == ".mp4"]
        if body.all and body.filename is not None or not body.all and body.filename is None:
            raise HTTPException(422, "Укажите одно видео или выберите все видео")
        if body.all:
            names = mp4_names
        else:
            name = body.filename
            if (not isinstance(name, str) or Path(name).name != name or "/" in name or "\\" in name
                    or Path(name).suffix.lower() != ".mp4" or name not in mp4_names):
                raise HTTPException(404, "Готовое видео не найдено")
            names = [name]
        if not names:
            raise HTTPException(404, "В задании нет готовых MP4-видео")

        output_dir = contained(current.job_dir(identifier) / "output", current.job_dir(identifier))
        sources = []
        for name in names:
            path = contained(output_dir / name, output_dir)
            if not path.is_file():
                raise HTTPException(404, "Одно из готовых видео недоступно")
            sources.append((name, path))

        # Determine destination folder:
        # 1. Direct API specification (headless/CI automation)
        # 2. Interactive native dialog with download_picker_lock
        if body.destination is not None:
            raw_dest = body.destination.strip()
            if not raw_dest:
                raise HTTPException(400, "Указана пустая папка для сохранения")
            try:
                destination = Path(raw_dest).resolve(strict=True)
            except (OSError, RuntimeError) as error:
                raise HTTPException(400, "Указанная папка недоступна") from error
            if not destination.is_dir():
                raise HTTPException(400, "Указанная папка недоступна")
            if destination == output_dir:
                raise HTTPException(400, "Выберите папку вне папки готовых видео")
        else:
            lock = request.app.state.download_picker_lock
            if not lock.acquire(blocking=False):
                raise HTTPException(409, "Выбор папки уже открыт")
            try:
                try:
                    selected = choose_download_directory()
                except Exception as error:
                    # Do not return tkinter diagnostics, which may contain local paths.
                    raise HTTPException(500, "Не удалось открыть окно выбора папки") from error
                if not selected:
                    return {"cancelled": True, "count": 0, "files": []}
                try:
                    destination = Path(selected).resolve(strict=True)
                except (OSError, RuntimeError) as error:
                    raise HTTPException(400, "Выбранная папка недоступна") from error
                if not destination.is_dir():
                    raise HTTPException(400, "Выбранная папка недоступна")
                if destination == output_dir:
                    raise HTTPException(400, "Выберите папку вне папки готовых видео")
            finally:
                lock.release()

        copied = []
        try:
            for name, source in sources:
                stem, suffix = Path(name).stem, Path(name).suffix
                index = 1
                while True:
                    output_name = name if index == 1 else f"{stem} ({index}){suffix}"
                    target = destination / output_name
                    if target.exists():
                        index += 1
                        continue
                    fd, temporary_name = tempfile.mkstemp(prefix=f".{stem}.", suffix=".tmp", dir=destination)
                    temporary = Path(temporary_name)
                    try:
                        with os.fdopen(fd, "wb") as outgoing:
                            with source.open("rb") as incoming:
                                shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
                            outgoing.flush()
                            os.fsync(outgoing.fileno())
                        # Same-directory rename is atomic and does not overwrite
                        # an existing destination on Windows.
                        os.rename(temporary, target)
                        copied.append(output_name)
                        break
                    except FileExistsError:
                        temporary.unlink(missing_ok=True)
                        index += 1
                    except OSError:
                        temporary.unlink(missing_ok=True)
                        raise
        except OSError as error:
            # Earlier completed copies remain; report their exact count. The
            # current partial file is removed before this response.
            return JSONResponse({"cancelled": False, "count": len(copied), "files": copied,
                                 "error": "Не удалось сохранить все видео в выбранную папку"}, 507)
        return {"cancelled": False, "count": len(copied), "files": copied}

    # Studio Edition: isolated finishing/caption APIs (never edits base plans).
    from .finishing import create_finishing_router
    application.include_router(create_finishing_router())

    static_legacy = config.ROOT / "app" / "static"
    dist_dir = config.ROOT / "frontend" / "dist"
    assets_dir = dist_dir / "assets"
    
    if assets_dir.is_dir():
        application.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
    if static_legacy.is_dir():
        application.mount("/static", StaticFiles(directory=static_legacy), name="static_legacy")
        
    # The user's Studio Edition HTML is the *canonical application*, not an
    # unserved file buried in frontend/public. Vite copies it to dist. A catch-all
    # that always returns React index.html previously made every preview of the
    # supplied design display the different React UI instead.
    studio_html = dist_dir / "studio-edition.html"
    studio_bridge = dist_dir / "studio-live-bridge.js"

    @application.api_route("/studio-live-bridge.js", methods=["GET", "HEAD"])
    def studio_bridge_asset():
        if not studio_bridge.is_file():
            raise HTTPException(503, "Studio Edition не собрана. Выполните npm run build в frontend.")
        return FileResponse(studio_bridge, media_type="text/javascript",
                            headers={"Cache-Control": "no-cache"})

    @application.api_route("/studio-edition.css", methods=["GET", "HEAD"])
    def studio_stylesheet():
        file = dist_dir / "studio-edition.css"
        if not file.is_file():
            raise HTTPException(503, "Studio Edition CSS не собран. Выполните npm run build в frontend.")
        return FileResponse(file, media_type="text/css", headers={"Cache-Control": "no-store"})

    @application.api_route("/studio-edition-app.js", methods=["GET", "HEAD"])
    def studio_application_script():
        file = dist_dir / "studio-edition-app.js"
        if not file.is_file():
            raise HTTPException(503, "Studio Edition JS не собран. Выполните npm run build в frontend.")
        return FileResponse(file, media_type="text/javascript", headers={"Cache-Control": "no-store"})

    @application.api_route("/{full_path:path}", methods=["GET", "HEAD"])
    def index(full_path: str, request: Request):
        if full_path.startswith(("api/", "assets/", "static/")):
            raise HTTPException(404)
        if full_path in {"legacy", "legacy/"}:
            if (static_legacy / "index.html").is_file():
                return FileResponse(static_legacy / "index.html")
            raise HTTPException(404, "Legacy UI not found")

        # A debug-only escape hatch; the previous React UX must never become
        # the default at /, /studio, /projects or a deep project link.
        if full_path == "react-debug" and (dist_dir / "index.html").is_file():
            return FileResponse(dist_dir / "index.html", headers={"Cache-Control": "no-cache"})
        if full_path in {"studio-edition.html", "studio-edition-reference.html"}:
            filename = full_path
            target = dist_dir / filename
            if target.is_file():
                return FileResponse(target, media_type="text/html",
                                    headers={"Cache-Control": "no-cache"})
            raise HTTPException(503, "Studio Edition не собрана. Выполните npm run build в frontend.")

        if not studio_html.is_file() or not studio_bridge.is_file():
            raise HTTPException(503, "Studio Edition не собрана. Выполните npm ci и npm run build в frontend.")

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
    return application


app = create_app()


def main():
    import uvicorn
    config.setup_environment()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8765, access_log=False))
    # Uvicorn config replaces logging globally and closes the launcher's
    # file handlers. Restore them before server startup can emit app events.
    from .run_logging import configure_logging
    configure_logging("studio")
    app.state.shutdown_callback = lambda: setattr(server, "should_exit", True)
    try:
        server.run()
    finally:
        app.state.shutdown_callback = None


if __name__ == "__main__":
    main()
