"""Real short ASR/VLM/render smoke using the first workspace episode."""
from pathlib import Path
import json
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import ROOT, TEMP, FFMPEG, setup_environment
from app.analysis import atomic_json
from app.pipeline import run_job

setup_environment()
episode = next(ROOT.glob('*.mp4'))
directory = TEMP / ('smoke-' + uuid.uuid4().hex)
directory.mkdir()
source = directory / 'sample.mp4'
subprocess.run([str(FFMPEG), '-y', '-v', 'error', '-ss', '35', '-i', str(episode), '-t', '35',
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '23', '-c:a', 'aac', str(source)], check=True)
atomic_json(directory / 'source.json', {'path': str(source), 'name': episode.name})
started = time.monotonic()
def report(stage, progress, message):
    print(f'{stage}: {progress:.0%} {message}', flush=True)
outputs = run_job(directory, report, lambda: False)
print(json.dumps({'directory': str(directory), 'outputs': outputs, 'elapsed': round(time.monotonic() - started, 2)}, ensure_ascii=False), flush=True)
