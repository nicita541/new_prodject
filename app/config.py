"""Workspace-only paths and offline runtime configuration."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / 'tools'
MODELS = ROOT / 'models'
DATA = ROOT / 'data'
JOBS = DATA / 'jobs'
IMPORTS = DATA / 'imports'
SETTINGS = DATA / 'settings'
TEMP = ROOT / 'temp'
CACHE = ROOT / 'cache'
MUSIC = ROOT / 'music'
MUSIC_CONFIG = MUSIC / 'config.json'
MUSIC_SETTINGS = SETTINGS / 'music.json'
FFMPEG = TOOLS / 'ffmpeg' / 'bin' / 'ffmpeg.exe'
FFPROBE = TOOLS / 'ffmpeg' / 'bin' / 'ffprobe.exe'
LLAMA = TOOLS / 'llama' / 'llama-server.exe'
ASR_MODEL = MODELS / 'whisper-large-v3'
VLM_MODEL = MODELS / 'qwen' / 'Qwen3.5-4B-UD-Q4_K_XL.gguf'
VLM_PROJECTOR = MODELS / 'qwen' / 'mmproj-F16.gguf'
STORY_MODEL = MODELS / 'qwen9' / 'Qwen3.5-9B-UD-Q4_K_XL.gguf'
STORY_PROJECTOR = MODELS / 'qwen9' / 'mmproj-F16.gguf'


def setup_environment() -> None:
    for path in (DATA, JOBS, IMPORTS, TEMP, CACHE):
        path.mkdir(parents=True, exist_ok=True)
    for name in ('TEMP', 'TMP', 'TMPDIR'):
        os.environ[name] = str(TEMP)
    os.environ.update({
        'HF_HOME': str(CACHE / 'huggingface'),
        'HUGGINGFACE_HUB_CACHE': str(CACHE / 'huggingface' / 'hub'),
        'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
        'PIP_CACHE_DIR': str(CACHE / 'pip'),
        'XDG_CACHE_HOME': str(CACHE),
        'TORCH_HOME': str(CACHE / 'torch'),
        'CUDA_CACHE_PATH': str(CACHE / 'cuda'),
        'PYTHONPYCACHEPREFIX': str(CACHE / 'pycache'),
        'PYTHONUTF8': '1',
    })
    dll_path = str(TOOLS / 'cuda' / 'bin')
    current_path = os.environ.get('PATH', '')
    if dll_path not in current_path.split(os.pathsep):
        os.environ['PATH'] = dll_path + os.pathsep + current_path


def readiness() -> dict:
    missing = []
    for name, path in (
        ('FFmpeg', FFMPEG), ('FFprobe', FFPROBE),
        ('llama.cpp', LLAMA), ('Qwen3.5-4B', VLM_MODEL),
        ('Визуальный проектор Qwen', VLM_PROJECTOR),
        ('Qwen3.5-9B для сокращения истории', STORY_MODEL),
        ('Визуальный проектор Qwen 9B', STORY_PROJECTOR),
        ('Whisper large-v3', ASR_MODEL / 'model.bin'),
        ('Токенизатор Whisper', ASR_MODEL / 'tokenizer.json'),
    ):
        if not path.is_file():
            missing.append(name)
    return {'ready': not missing, 'missing': missing}
