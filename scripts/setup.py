"""Explicit portable installer. Network is used only by this command."""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

try:
    from .download_ranged import download as download_ranged, workspace_path
except ImportError:  # Direct `python scripts/setup.py` entry point.
    from download_ranged import download as download_ranged, workspace_path

ROOT = Path(__file__).resolve().parent.parent
TEMP = ROOT / 'temp'
CACHE = ROOT / 'cache'
TOOLS = ROOT / 'tools'
MODELS = ROOT / 'models'
for directory in (TEMP, CACHE / 'downloads', TOOLS, MODELS):
    directory.mkdir(parents=True, exist_ok=True)
os.environ.update(TEMP=str(TEMP), TMP=str(TEMP), TMPDIR=str(TEMP),
                  PIP_CACHE_DIR=str(CACHE / 'pip'), HF_HOME=str(CACHE / 'huggingface'),
                  PYTHONPYCACHEPREFIX=str(CACHE / 'pycache'), PYTHONUTF8='1')

PYTHON_URL = 'https://github.com/astral-sh/python-build-standalone/releases/download/20260929/cpython-3.12.14%2B20260929-x86_64-pc-windows-msvc-install_only_stripped.tar.gz'
LLAMA_TAG = 'b11316'
QWEN_REV = 'e87f176479d0855a907a41277aca2f8ee7a09523'
QWEN9_REV = '3885219b6810b007914f3a7950a8d1b469d598a5'
WHISPER_REV = 'edaa852ec7e145841d8ffdb056a99866b5f0a478'
PYTHON_SHA256 = 'f38e68f4d612ade6dd50c894fc80b14c0be0c3b5201145d6fff5f20b9323204d'
LLAMA_SHA256 = '2d84b2b44ce88faf86e7d913d543c611d09901be28a937b890e59704e86d1c34'
MODEL_HASHES = {
    'Qwen3.5-4B-UD-Q4_K_XL.gguf': 'b252c5610a42ca82d20fe2a12813e9d069eed89292907e26c783eeb0bc961bc7',
    'mmproj-F16.gguf': 'cd88edcf8d031894960bb0c9c5b9b7e1fea6ebee02b9f7ce925a00d12891f864',
    'model.bin': '69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1',
}
STORY_MODEL_FILES = {
    'Qwen3.5-9B-UD-Q4_K_XL.gguf': {
        'size': 5966095584,
        'sha256': '6f5d30666c2d8ae16a306e616d95341dcf3cc46810df84d7e6f5a7d1e4c1b293',
    },
    'mmproj-F16.gguf': {
        'size': 918166080,
        'sha256': 'f70dc3509053962b0d0d3ee8a7eacebf5d60aa560cad78254ae8698516ae029f',
    },
}


def download(url: str, destination: Path, expected_hash: str | None = None) -> Path:
    destination = workspace_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size > 0:
        if expected_hash is None or hashlib.file_digest(destination.open('rb'), 'sha256').hexdigest() == expected_hash:
            return destination
        raise RuntimeError(f'Checksum mismatch: {destination.name}')
    partial = destination.with_suffix(destination.suffix + '.partial')
    request = urllib.request.Request(url, headers={'User-Agent': 'anime-shorts-local/1.0'})
    print(f'Download: {destination.name}', flush=True)
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=120) as response, partial.open('wb') as output:
        while chunk := response.read(4 * 1024 * 1024):
            output.write(chunk)
            digest.update(chunk)
    if expected_hash and digest.hexdigest() != expected_hash:
        raise RuntimeError(f'Checksum mismatch: {destination.name}')
    partial.replace(destination)
    print(f'Ready: {destination.name} ({destination.stat().st_size // 1048576} MiB)', flush=True)
    return destination


def unzip(archive: Path, target: Path, dll_only: bool = False) -> None:
    target = workspace_path(target)
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            if member.is_dir():
                continue
            relative = Path(member.filename)
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('Unsafe archive entry')
            if dll_only:
                if relative.suffix.lower() != '.dll' and 'license' not in relative.name.lower():
                    continue
                output = target / relative.name
            else:
                output = target / relative
            output = workspace_path(output)
            output.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(member) as source, output.open('wb') as sink:
                shutil.copyfileobj(source, sink)


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if mode not in ('all', 'runtime', 'models', 'packages'):
        raise SystemExit('Use: setup.py [all|runtime|models|packages]')
    if mode in ('all', 'runtime'):
        archive = download(PYTHON_URL, CACHE / 'downloads' / 'python.tar.gz', PYTHON_SHA256)
        if not (TOOLS / 'python' / 'python.exe').exists():
            with tarfile.open(archive) as bundle:
                bundle.extractall(TOOLS, filter='data')
        ffmpeg = TOOLS / 'ffmpeg' / 'bin' / 'ffmpeg.exe'
        if not ffmpeg.exists():
            existing = shutil.which('ffmpeg')
            if not existing:
                raise RuntimeError('Put a portable FFmpeg distribution with libass into tools/ffmpeg (bin/ffmpeg.exe and bin/ffprobe.exe)')
            source = Path(existing).parent.parent
            if source == (TOOLS / 'ffmpeg').resolve():
                raise RuntimeError('Invalid FFmpeg distribution')
            shutil.copytree(source, TOOLS / 'ffmpeg', dirs_exist_ok=True)
        # Vulkan backend is portable and supports RTX 50-series without a system CUDA toolkit.
        llama_url = f'https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_TAG}/llama-{LLAMA_TAG}-bin-win-vulkan-x64.zip'
        llama_archive = download(llama_url, CACHE / 'downloads' / 'llama-vulkan.zip', LLAMA_SHA256)
        unzip(llama_archive, TOOLS / 'llama')
        cublas_info = json.loads(urllib.request.urlopen('https://developer.download.nvidia.com/compute/cuda/redist/redistrib_12.9.1.json').read())['libcublas']['windows-x86_64']
        cudnn_info = json.loads(urllib.request.urlopen('https://developer.download.nvidia.com/compute/cudnn/redist/redistrib_9.11.0.json').read())['cudnn']['windows-x86_64']['cuda12']
        specs = [('cublas.zip', 'https://developer.download.nvidia.com/compute/cuda/redist/', cublas_info),
                 ('cudnn.zip', 'https://developer.download.nvidia.com/compute/cudnn/redist/', cudnn_info)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(download, base + info['relative_path'], CACHE / 'downloads' / name, info['sha256']) for name, base, info in specs]
            for future in futures:
                unzip(future.result(), TOOLS / 'cuda' / 'bin', dll_only=True)
    if mode in ('all', 'packages'):
        interpreter = TOOLS / 'python' / 'python.exe'
        wheels = CACHE / 'wheels'
        wheels.mkdir(exist_ok=True)
        requirements = ROOT / 'requirements.lock.txt'
        if not requirements.exists():
            requirements = ROOT / 'requirements.in'
        subprocess.run([str(interpreter), '-m', 'pip', 'download', '--dest', str(wheels), '-r', str(requirements)], check=True, cwd=ROOT)
        subprocess.run([str(interpreter), '-m', 'pip', 'install', '--no-index', '--find-links', str(wheels), '-r', str(requirements)], check=True, cwd=ROOT)
        frozen = subprocess.check_output([str(interpreter), '-m', 'pip', 'freeze'], cwd=ROOT, text=True)
        (ROOT / 'requirements.lock.txt').write_text(frozen, encoding='utf-8')
    if mode in ('all', 'models'):
        specs = []
        for name in ('Qwen3.5-4B-UD-Q4_K_XL.gguf', 'mmproj-F16.gguf'):
            specs.append((f'https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/{QWEN_REV}/{name}?download=true', MODELS / 'qwen' / name))
        for name in ('config.json', 'model.bin', 'preprocessor_config.json', 'tokenizer.json', 'vocabulary.json'):
            specs.append((f'https://huggingface.co/Systran/faster-whisper-large-v3/resolve/{WHISPER_REV}/{name}?download=true', MODELS / 'whisper-large-v3' / name))
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(download, url, path, MODEL_HASHES.get(path.name)) for url, path in specs]
            for future in futures:
                future.result()
        # Download the two 9B artifacts sequentially, each with at most four
        # ranged connections. Their projector basename also exists under
        # qwen/; the separate spec map prevents accidental 4B hash reuse.
        story_specs = []
        for name, identity in STORY_MODEL_FILES.items():
            url = f'https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/resolve/{QWEN9_REV}/{name}?download=true'
            path = workspace_path(MODELS / 'qwen9' / name)
            download_ranged(url, path, identity['size'], identity['sha256'],
                            log=lambda message: print(message, flush=True))
            story_specs.append((url, path))
        model_hashes = {}
        for _, path in specs + story_specs:
            with path.open('rb') as stream:
                model_hashes[str(path.relative_to(ROOT))] = hashlib.file_digest(stream, 'sha256').hexdigest()
        manifest = {'python': '3.12.14', 'llama': LLAMA_TAG, 'backend': 'Vulkan',
                    'qwen_revision': QWEN_REV, 'qwen9_revision': QWEN9_REV,
                    'whisper_revision': WHISPER_REV, 'models': model_hashes}
        manifest_path = MODELS / 'manifest.json'
        partial_manifest = MODELS / 'manifest.json.partial'
        partial_manifest.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        partial_manifest.replace(manifest_path)
    print('Portable setup complete.', flush=True)


if __name__ == '__main__':
    main()
