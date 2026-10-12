"""MCP-only contracts, bounded responses and replay protection; no pipeline imports."""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Callable

from filelock import FileLock, Timeout
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from app.json_store import atomic_json, read_json
from app.content_identity import digest
from app.run_logging import scrub

ID = Annotated[str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")]
OP = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{8,100}$")]
LIMIT = Annotated[int, Field(ge=1, le=100)]
OFFSET = Annotated[int, Field(ge=0, le=1000000)]
TEXT = Annotated[str, Field(min_length=1, max_length=200)]
MAX_RESULT = 192 * 1024


class MCPError(Exception):
    def __init__(self, code: str, message: str, *, details=None):
        super().__init__(message)
        self.code, self.details = code, details


def redact(value):
    if isinstance(value, dict):
        return {str(k): "[REDACTED]" if re.search(
            r"(?i)^(api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|authorization|credentials|private[_-]?key)$", str(k))
            else redact(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return scrub(value, limit=24000)
    if isinstance(value, float) and not __import__('math').isfinite(value):
        return None
    return value


def page(items, offset=0, limit=30):
    return {"items": items[offset:offset + limit], "total": len(items),
            "next_offset": offset + limit if offset + limit < len(items) else None}


def resolve_under(root: Path, value: str | Path) -> Path:
    candidate = Path(value)
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise MCPError("path_denied", "Путь за пределами разрешённой папки")
    return resolved


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


@dataclass
class ToolSpec:
    name: str
    description: str
    model: type[BaseModel]
    handler: Callable
    mutating: bool


class Registry:
    def __init__(self, prefix, journal=None):
        self.prefix, self.journal, self.tools = prefix, journal, {}

    def add(self, name, description, fields, handler, *, mutating=False):
        if mutating:
            fields = {**fields, "operation_id": (OP, ...)}
        full_name = self.prefix + name
        self.tools[full_name] = ToolSpec(full_name, description,
            create_model(full_name + "Arguments", __base__=Arguments, **fields), handler, mutating)

    async def invoke(self, name, arguments):
        try:
            if name not in self.tools:
                raise MCPError("unknown_tool", "Инструмент не доступен в этом подключении")
            spec = self.tools[name]
            values = spec.model.model_validate(arguments).model_dump(mode="json")
            async def action():
                return await spec.handler(**{k: v for k, v in values.items() if not spec.mutating or k != "operation_id"})
            data = await self.journal.execute(values["operation_id"], name, values, action) if spec.mutating else await action()
            result = {"schema_version": 1, "ok": True, "data": redact(data)}
            if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_RESULT:
                raise MCPError("result_too_large", "Ответ слишком велик; уменьшите страницу или запросите отдельный артефакт")
            return result
        except ValidationError as error:
            return {"schema_version": 1, "ok": False, "error": {"code": "invalid_arguments",
                "message": "Аргументы не соответствуют схеме", "details": error.errors(include_input=False, include_context=False)}}
        except MCPError as error:
            return {"schema_version": 1, "ok": False, "error": {"code": error.code,
                "message": scrub(str(error)), "details": redact(error.details)}}
        except (OSError, ValueError, KeyError) as error:
            return {"schema_version": 1, "ok": False, "error": {"code": "data_error",
                "message": scrub(str(error)), "type": type(error).__name__}}
        except Exception as error:
            return {"schema_version": 1, "ok": False, "error": {"code": "internal_error",
                "message": "Внутренняя ошибка MCP; операция автоматически не повторяется", "type": type(error).__name__}}


class ReplayJournal:
    """Cross-process replay guard. An interrupted pending action is never relaunched.

    Cancellation of a protocol call does not cancel an accepted mutation: the task
    keeps the OS lock until its result has been persisted. Process death leaves an
    explicit uncertain record for inspection instead of risking a second launch.
    """
    def __init__(self, directory: Path, *, root: Path | None = None):
        self.directory = directory
        self.root = (root or directory.parent).resolve()
        self.pending = set()

    async def inspect(self, operation_id):
        directory = resolve_under(self.root, self.directory)
        path = resolve_under(directory, operation_id + '.json')
        if not path.is_file():
            raise MCPError('not_found', 'operation_id не найден')
        if path.stat().st_size > MAX_RESULT:
            raise MCPError('result_too_large', 'Запись операции слишком велика')
        record = read_json(path)
        return {**record, 'note': 'pending может означать выполняющийся или прерванный вызов; проверьте состояние задания перед новой командой'}

    async def execute(self, operation_id, name, arguments, action):
        task = asyncio.create_task(self._execute(operation_id, name, arguments, action))
        self.pending.add(task)
        task.add_done_callback(self.pending.discard)
        return await asyncio.shield(task)

    async def _execute(self, operation_id, name, arguments, action):
        directory = resolve_under(self.root, self.directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = resolve_under(directory, operation_id + ".json")
        lock = FileLock(str(resolve_under(directory, path.with_suffix(".lock"))))
        try:
            lock.acquire(timeout=0)
        except Timeout:
            raise MCPError("operation_in_progress", "Этот operation_id уже выполняется") from None
        try:
            identity = digest({"tool": name, "arguments": arguments})
            previous = read_json(path)
            if previous:
                if previous["identity"] != identity:
                    raise MCPError("operation_conflict", "operation_id уже использован с другими аргументами")
                if previous["state"] == "done":
                    return previous["result"]
                if previous["state"] == "rejected":
                    raise MCPError(previous["error"]["code"], previous["error"]["message"])
                raise MCPError("operation_uncertain", "Предыдущий вызов прерван. Проверьте состояние задания; автоматический повтор запрещён")
            atomic_json(path, {"identity": identity, "tool": name, "state": "pending"})
            try:
                result = await action()
            except MCPError as error:
                # Only known pre-operation / HTTP 4xx rejections are safe to persist.
                if error.code not in {"backend_unavailable", "backend_failure", "backend_invalid_response"}:
                    atomic_json(path, {"identity": identity, "tool": name, "state": "rejected",
                        "error": {"code": error.code, "message": scrub(str(error))}})
                raise
            atomic_json(path, {"identity": identity, "tool": name, "state": "done", "result": redact(result)})
            return result
        finally:
            lock.release()

    async def drain(self):
        if self.pending:
            await asyncio.gather(*self.pending, return_exceptions=True)
