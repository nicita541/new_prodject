"""HTTP byte-range delivery of caller-approved media paths."""
from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse


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
