"""Explicit, resumable ranged downloads; all artifacts stay in this workspace.

Usage: tools/python/python.exe scripts/download_ranged.py URL DEST SIZE SHA256
Default: 8 MiB chunks, at most four connections, 30s socket timeout, 3 attempts.
Use --chunk-mib 4 for a first benchmark, or --self-test for local-only checks.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
MIB = 1024 * 1024


class DownloadError(RuntimeError):
    pass


def workspace_path(path: Path) -> Path:
    value = path.resolve()
    if not value.is_relative_to(ROOT.resolve()):
        raise ValueError("Destination and all checkpoints must be inside F:\\new_prodject")
    return value


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save_json(path: Path, value) -> None:
    partial = path.with_suffix(path.suffix + ".partial")
    with partial.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(partial, path)


class DownloadLock:
    def __init__(self, path: Path):
        self.stream = path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                if path.stat().st_size == 0:
                    self.stream.write(b"0")
                    self.stream.flush()
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            raise DownloadError("Another ranged download already owns this destination") from None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if os.name == "nt":
            import msvcrt
            self.stream.seek(0)
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        self.stream.close()


def download(url: str, destination: Path, size: int, sha256: str, *, chunk_size: int = 8 * MIB,
             workers: int = 4, attempts: int = 3, timeout: float = 30,
             keep_chunks: bool = False, log=print) -> Path:
    """Download a pinned file without accepting silent full-body range fallbacks.

    A checkpoint consists of both its exact bytes and a local SHA256 sidecar.
    The final pinned SHA256 remains the source-of-truth integrity check.
    """
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Use an HTTP(S) URL without embedded credentials")
    if size <= 0 or chunk_size <= 0 or not 1 <= workers <= 4 or not 1 <= attempts <= 3 or not 0 < timeout <= 30:
        raise ValueError("Invalid size, chunk size, workers, retry count or timeout")
    sha256 = sha256.lower()
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ValueError("Expected SHA256 must contain 64 hexadecimal characters")
    destination = workspace_path(Path(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    directory = workspace_path(destination.parent / ("." + destination.name + ".chunks"))
    lock_path = workspace_path(destination.parent / ("." + destination.name + ".range.lock"))
    assembly = workspace_path(destination.parent / ("." + destination.name + ".ranged.partial"))
    count = (size + chunk_size - 1) // chunk_size
    print_lock = threading.Lock()
    def emit(message):
        with print_lock:
            log(message)
    def paths(index):
        return directory / f"{index:06}.bin", directory / f"{index:06}.json"

    with DownloadLock(lock_path):
        if destination.is_file() and destination.stat().st_size == size and file_hash(destination) == sha256:
            emit(f"Already verified: {destination.name}")
            return destination
        directory.mkdir(parents=True, exist_ok=True)
        manifest = directory / "manifest.json"
        identity = {"version": 1, "size": size, "sha256": sha256, "chunk_size": chunk_size}
        if manifest.is_file():
            try:
                previous = json.loads(manifest.read_text("utf-8"))
            except (ValueError, OSError):
                raise DownloadError("Unreadable range checkpoint manifest") from None
            if previous != identity:
                raise DownloadError("Checkpoint settings differ; use the previous chunk size or a new destination")
        else:
            save_json(manifest, identity)
        emit(f"Ranged download: {destination.name}, {count} chunks, {workers} workers")
        stopped = threading.Event()

        def fetch(index):
            start = index * chunk_size
            end = min(size, start + chunk_size) - 1
            expected = end - start + 1
            target, metadata = paths(index)
            temporary = target.with_suffix(".partial")
            if target.is_file() and metadata.is_file() and target.stat().st_size == expected:
                try:
                    saved = json.loads(metadata.read_text("utf-8"))
                    if saved == {"start": start, "end": end, "sha256": file_hash(target)}:
                        return expected, True
                except (ValueError, OSError):
                    pass
            for attempt in range(attempts):
                if stopped.is_set():
                    raise DownloadError("Download interrupted; verified chunks can be resumed")
                try:
                    request = urllib.request.Request(url, headers={
                        "Range": f"bytes={start}-{end}", "Accept-Encoding": "identity",
                        "User-Agent": "anime-shorts-local/1.0"})
                    # Default urllib HTTPS verification remains enabled.
                    with urllib.request.urlopen(request, timeout=timeout) as response:
                        status = response.status
                        if status == 206:
                            wanted = f"bytes {start}-{end}/{size}"
                            if response.headers.get("Content-Range", "").strip() != wanted:
                                raise DownloadError("Server returned an incorrect Content-Range")
                        elif status == 200 and start == 0 and expected == size:
                            pass  # A single chunk really is the entire expected file.
                        else:
                            raise DownloadError("Server did not honor the requested range")
                        encoding = response.headers.get("Content-Encoding", "identity").lower()
                        if encoding not in {"", "identity"}:
                            raise DownloadError("Encoded range bodies are not accepted")
                        length = response.headers.get("Content-Length")
                        if length is not None and int(length) != expected:
                            raise DownloadError("Range Content-Length differs from expected size")
                        digest = hashlib.sha256()
                        received = 0
                        with temporary.open("wb") as output:
                            while block := response.read(min(64 * 1024, expected - received + 1)):
                                received += len(block)
                                if received > expected:
                                    raise DownloadError("Range body is larger than expected")
                                output.write(block)
                                digest.update(block)
                            if received != expected:
                                raise DownloadError("Range body is incomplete")
                            output.flush()
                            os.fsync(output.fileno())
                    os.replace(temporary, target)
                    save_json(metadata, {"start": start, "end": end, "sha256": digest.hexdigest()})
                    return expected, False
                except (OSError, urllib.error.URLError, http.client.HTTPException, ValueError, DownloadError) as error:
                    if attempt + 1 == attempts:
                        # Do not echo URLs, redirect signatures, or credentials.
                        raise DownloadError(f"Chunk {index + 1}/{count} failed after {attempts} attempts ({type(error).__name__})") from None
                    emit(f"Retry chunk {index + 1}/{count}: {attempt + 2}/{attempts} ({type(error).__name__})")
                    stopped.wait(min(2 ** attempt, 4))
                finally:
                    temporary.unlink(missing_ok=True)

        complete = 0
        resumed = 0
        try:
            # Only four pending futures exist; no unbounded task submission.
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                active = {}
                next_index = 0
                try:
                    while next_index < count or active:
                        while len(active) < workers and next_index < count:
                            future = executor.submit(fetch, next_index)
                            active[future] = next_index
                            next_index += 1
                        done, _ = concurrent.futures.wait(active, return_when=concurrent.futures.FIRST_COMPLETED)
                        for future in done:
                            del active[future]
                            _received, reused = future.result()
                            complete += 1
                            resumed += int(reused)
                        emit(f"Verified chunks: {complete}/{count}; resumed: {resumed}")
                except BaseException:
                    # Signal other workers before executor.__exit__ waits for
                    # in-flight reads; they stop instead of entering retries.
                    stopped.set()
                    for future in active:
                        future.cancel()
                    raise
        except BaseException:
            stopped.set()
            raise
        digest = hashlib.sha256()
        try:
            with assembly.open("wb") as output:
                for index in range(count):
                    with paths(index)[0].open("rb") as part:
                        while block := part.read(MIB):
                            output.write(block)
                            digest.update(block)
                output.flush()
                os.fsync(output.fileno())
            if assembly.stat().st_size != size or digest.hexdigest() != sha256:
                raise DownloadError("Final pinned SHA256 or size mismatch; destination was not changed")
            os.replace(assembly, destination)
        finally:
            assembly.unlink(missing_ok=True)
        emit(f"SHA256 verified: {destination.name} ({size} bytes)")
        if not keep_chunks:
            # Remove only our known checkpoint files; no recursive deletion.
            for index in range(count):
                for path in paths(index):
                    path.unlink(missing_ok=True)
            manifest.unlink(missing_ok=True)
            try:
                directory.rmdir()
            except OSError:
                pass
        return destination


def self_test() -> bool:
    """Fake loopback HTTP only: range validation, retries, resume and hash checks."""
    import http.server
    import shutil
    import socketserver
    import unittest
    import uuid

    class Tests(unittest.TestCase):
        def setUp(self):
            self.root = ROOT / "temp" / ("range_test_" + uuid.uuid4().hex)
            self.root.mkdir(parents=True)
            self.payload = bytes(range(256)) * 20 + b"tail"
            self.destination = self.root / "Русская модель с пробелами.gguf"
            self.sha = hashlib.sha256(self.payload).hexdigest()
            self.requests = []
            self.mode = "range"
            self.fail_start = None
            self.fail_once = False
            owner = self
            class Handler(http.server.BaseHTTPRequestHandler):
                def log_message(self, *_):
                    pass
                def do_GET(self):
                    left, right = map(int, self.headers["Range"].removeprefix("bytes=").split("-"))
                    owner.requests.append((left, right))
                    if left == owner.fail_start:
                        if owner.fail_once:
                            owner.fail_start = None
                        self.send_response(503)
                        self.end_headers()
                        return
                    body = owner.payload[left:right + 1]
                    status = 200 if owner.mode == "full" else 206
                    self.send_response(status)
                    header = f"bytes {left}-{right}/{len(owner.payload)}"
                    if owner.mode == "wrong_range":
                        header = f"bytes {left + 1}-{right}/{len(owner.payload)}"
                    self.send_header("Content-Range", header)
                    if owner.mode == "short":
                        body = body[:-1]
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    try:
                        self.wfile.write(body)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
            class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
                daemon_threads = True
            self.server = Server(("127.0.0.1", 0), Handler)
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            self.url = f"http://127.0.0.1:{self.server.server_port}/fake-file"
        def tearDown(self):
            self.server.shutdown()
            self.server.server_close()
            self.thread.join()
            if self.root.resolve().is_relative_to((ROOT / "temp").resolve()):
                shutil.rmtree(self.root)
        def invoke(self, **kwargs):
            return download(self.url, self.destination, len(self.payload), self.sha,
                            chunk_size=1024, timeout=2, log=lambda _: None, **kwargs)
        def test_hash_and_resume_after_interrupted_chunk(self):
            self.fail_start = 2048
            with self.assertRaises(DownloadError):
                self.invoke(workers=1, attempts=1)
            self.assertFalse(self.destination.exists())
            self.assertIn((0, 1023), self.requests)
            self.assertIn((1024, 2047), self.requests)
            self.fail_start = None
            self.requests.clear()
            self.invoke(workers=4)
            self.assertEqual(self.destination.read_bytes(), self.payload)
            self.assertNotIn((0, 1023), self.requests)
            self.assertNotIn((1024, 2047), self.requests)
            self.assertEqual(file_hash(self.destination), self.sha)
            self.assertFalse((self.root / ("." + self.destination.name + ".chunks")).exists())
        def test_incorrect_ranges_and_short_bodies_are_rejected(self):
            for mode in ("wrong_range", "short", "full"):
                with self.subTest(mode=mode):
                    self.mode = mode
                    with self.assertRaises(DownloadError):
                        self.invoke(workers=1, attempts=1)
                    self.assertFalse(self.destination.exists())
        def test_only_whole_file_200_is_accepted(self):
            self.mode = "full"
            download(self.url, self.destination, len(self.payload), self.sha,
                     chunk_size=len(self.payload), timeout=2, log=lambda _: None)
            self.assertEqual(self.destination.read_bytes(), self.payload)
        def test_hash_mismatch_preserves_existing_destination(self):
            self.destination.write_bytes(b"previous destination")
            with self.assertRaisesRegex(DownloadError, "SHA256"):
                download(self.url, self.destination, len(self.payload), "0" * 64,
                         chunk_size=1024, timeout=2, log=lambda _: None)
            self.assertEqual(self.destination.read_bytes(), b"previous destination")
            self.assertFalse((self.root / ("." + self.destination.name + ".ranged.partial")).exists())
        def test_corrupted_checkpoint_is_refetched_and_transient_http_failure_retries(self):
            self.fail_start = 2048
            with self.assertRaises(DownloadError):
                self.invoke(workers=1, attempts=1)
            directory = self.root / ("." + self.destination.name + ".chunks")
            (directory / "000000.bin").write_bytes(b"X" * 1024)
            self.requests.clear()
            self.fail_once = True
            self.invoke(workers=1)
            self.assertIn((0, 1023), self.requests)
            self.assertEqual(self.requests.count((2048, 3071)), 2)
            self.assertEqual(file_hash(self.destination), self.sha)
        def test_non_workspace_destination_and_credentials_rejected(self):
            with self.assertRaises(ValueError):
                download(self.url, ROOT.parent / "outside.gguf", len(self.payload), self.sha)
            with self.assertRaises(ValueError):
                download("https://user:password@example.com/file", self.destination, len(self.payload), self.sha)

    return unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests)).wasSuccessful()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?")
    parser.add_argument("destination", type=Path, nargs="?")
    parser.add_argument("size", type=int, nargs="?")
    parser.add_argument("sha256", nargs="?")
    parser.add_argument("--chunk-mib", type=int, choices=range(4, 65), default=8)
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=4)
    parser.add_argument("--keep-chunks", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        raise SystemExit(0 if self_test() else 1)
    if None in (args.url, args.destination, args.size, args.sha256):
        parser.error("URL DEST SIZE SHA256 are required")
    try:
        download(args.url, args.destination, args.size, args.sha256,
                 chunk_size=args.chunk_mib * MIB, workers=args.workers, keep_chunks=args.keep_chunks,
                 log=lambda message: print(message, flush=True))
    except (ValueError, DownloadError, OSError) as error:
        # Keep URL/redirect details out of CLI output.
        parser.exit(1, f"Ranged download failed: {str(error) if isinstance(error, (ValueError, DownloadError)) else type(error).__name__}\n")


if __name__ == "__main__":
    main()
