"""Create a small synthetic finished job in THIS worktree. No AI models used."""
from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import config
from app.jobs import JobManager, atomic_json, now
from app.library import Library

MANIFEST = config.DATA / "studio-demo.json"


def ffmpeg(*args: str) -> None:
    subprocess.run([str(config.FFMPEG), "-hide_banner", "-loglevel", "error", "-y", *args],
                   check=True, cwd=str(ROOT), timeout=90)


def main() -> None:
    config.setup_environment()
    if MANIFEST.exists():
        saved = json.loads(MANIFEST.read_text(encoding="utf-8"))
        job_dir = config.JOBS / saved.get("job_id", "_invalid")
        if (job_dir / "job.json").is_file() and (job_dir / "output" / "part_001.mp4").is_file():
            print("Visual demo already prepared: " + saved["url"])
            return
        raise RuntimeError("Demo metadata found without files: data/studio-demo.json")

    if not config.FFMPEG.is_file():
        raise RuntimeError("FFmpeg is missing from THIS worktree: tools/ffmpeg/bin/ffmpeg.exe")

    # Worktree-local lock prevents preparing demo while its own server is running.
    manager = JobManager(config.ROOT)
    try:
        demo_path = config.IMPORTS / ("studio-demo-" + uuid.uuid4().hex[:8])
        demo_path.mkdir(parents=True)
        source = demo_path / "studio-demo-source.mp4"
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24",
               "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
               "-t", "12", "-c:v", "libx264", "-preset", "ultrafast",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source))
        sources = manager.list_sources()
        source_record = next(row for row in sources
                             if manager.source(row["id"])["path"] == str(source.resolve()))
        library = Library(manager)
        project = library.create_project("KADR Studio — демо")
        episode = library.create_episode(project["id"], 1)
        library.save_episode(episode["id"], source_record["id"], {
            "layout": "portrait", "caption_style": "classic", "analysis_provider": "local"})
        job_id = str(uuid.uuid4())
        job_dir = manager.job_dir(job_id)
        output_dir = job_dir / "output"
        output_dir.mkdir(parents=True)
        phrases = (
            "ТВОЯ ИСТОРИЯ НАЧИНАЕТСЯ ЗДЕСЬ",
            "КАЖДЫЙ КАДР ИМЕЕТ ЗНАЧЕНИЕ",
            "СОЗДАВАЙ SHORTS В KADR STUDIO",
        )
        parts, outputs = [], []
        for index, phrase in enumerate(phrases, 1):
            offset = (index - 1) * 4
            name = f"part_{index:03d}.mp4"
            ffmpeg("-ss", str(offset), "-t", "4", "-i", str(source),
                   "-vf", "scale=360:640:force_original_aspect_ratio=increase,crop=360:640",
                   "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                   "-c:a", "aac", "-movflags", "+faststart", str(output_dir / name))
            srt = f"part_{index:03d}.srt"
            (output_dir / srt).write_text(
                "1\n00:00:00,200 --> 00:00:03,200\n" + phrase + "\n", encoding="utf-8")
            outputs += [name, srt]
            parts.append({
                "index": index, "duration": 4.0, "layout": "portrait",
                "caption_style": "classic", "music_track": None,
                "cuts": [{"start": offset, "end": offset + 4,
                          "focus": [{"time": offset, "x": .5, "y": .5, "confidence": 1},
                                    {"time": offset + 4, "x": .5, "y": .5, "confidence": 1}]}],
                "subtitles": [{"start": .2, "end": 3.2, "text": phrase}],
            })
        atomic_json(job_dir / "source.json",
                    {"path": str(source.resolve()), "name": source.name})
        atomic_json(job_dir / "plan.json", {"source": {"duration": 12.0}, "parts": parts})
        atomic_json(job_dir / "job.json", {
            "id": job_id, "episode_id": episode["id"], "source_id": source_record["id"],
            "source_name": source.name, "status": "completed", "progress": 1.0,
            "stage": "completed", "message": "Синтетическая демосерия",
            "created_at": now(), "updated_at": now(), "error": None,
            "cancel_requested": False, "analysis_provider": "local",
            "layout": "portrait", "caption_style": "classic", "outputs": outputs,
        })
        link = ("http://127.0.0.1:8766/episode/" + episode["id"] +
                "/finishing/" + job_id)
        atomic_json(MANIFEST, {"url": link, "job_id": job_id,
                               "episode_id": episode["id"], "synthetic": True})
        print("Three synthetic Shorts ready. Open: " + link)
    finally:
        manager.close()


if __name__ == "__main__":
    main()
