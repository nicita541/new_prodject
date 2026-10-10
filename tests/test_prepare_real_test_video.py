"""Acceptance tests for selecting a real story video without mutating originals."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from app import config
from scripts.prepare_real_test_video import prepare


@pytest.fixture
def qa_workspace():
    config.TEMP.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="story-selection-", dir=config.TEMP) as name:
        root = Path(name)
        yield root


def mock_media(duration: float, audio: bool = True) -> dict:
    return {"duration": duration, "has_audio": audio}


def test_real_180_second_in_project_keeps_original_unchanged(qa_workspace):
    source = qa_workspace / "video.mp4"
    source.write_bytes(b"DO NOT MODIFY ORIGINAL")
    destination = qa_workspace / "input"
    with patch("scripts.prepare_real_test_video.probe_media",
               return_value=mock_media(180)),          patch("scripts.prepare_real_test_video.run_command") as run_command:
        result = prepare(source, destination)
    assert result == source
    assert source.read_bytes() == b"DO NOT MODIFY ORIGINAL"
    assert (destination / "selected-source.txt").read_text("utf-8") == str(source)
    run_command.assert_not_called()


def test_long_story_uses_ffmpeg_180_seconds_without_touching_original(qa_workspace):
    source = qa_workspace / "episode.mkv"
    source.write_bytes(b"original source episode")
    destination = qa_workspace / "extracted"
    def fake_render(argv, work, timeout):
        assert "-ss" in argv and argv[argv.index("-ss") + 1] == "300.0"
        assert "-t" in argv and argv[argv.index("-t") + 1] == "180"
        assert "-map" in argv and "0:a:0" in argv
        Path(argv[-1]).write_bytes(b"processed video")

    with patch("scripts.prepare_real_test_video.probe_media",
               side_effect=[mock_media(1380), mock_media(180)]) as probe,          patch("scripts.prepare_real_test_video.run_command",
               side_effect=fake_render) as render:
        result = prepare(source, destination, start_seconds=300)
    assert result == destination / "story-180s.mp4"
    assert result.read_bytes() == b"processed video"
    assert source.read_bytes() == b"original source episode"
    assert probe.call_count == 2 and render.call_count == 1
    assert (destination / "selected-source.txt").read_text("utf-8") == str(result)


def test_russian_track_selected_when_source_has_multiple_audio_tracks(qa_workspace):
    source = qa_workspace / "episode.mkv"
    source.write_bytes(b"unaltered multiple-track episode")
    directory = qa_workspace / "output"
    def fake_render(args, _, timeout):
        assert "-map" in args
        assert "0:a:2" in args, "must use probe-selected Russian track"
        Path(args[-1]).write_bytes(b"clip")
    with patch("scripts.prepare_real_test_video.probe_media", side_effect=[
        {"duration": 1380.0, "has_audio": True, "audio_stream": 2},
        mock_media(180.0)
    ]), patch("scripts.prepare_real_test_video.run_command", side_effect=fake_render):
        result = prepare(source, directory)
    assert result.exists()
    assert source.read_bytes() == b"unaltered multiple-track episode"


def test_missing_audio_and_short_inputs_fail_explicitly(qa_workspace):
    source = qa_workspace / "no-dialogue.mp4"
    source.write_bytes(b"source")
    target = qa_workspace / "target"
    with patch("scripts.prepare_real_test_video.probe_media",
               return_value=mock_media(180, False)):
        with pytest.raises(ValueError, match="spoken-audio"):
            prepare(source, target)
    with patch("scripts.prepare_real_test_video.probe_media",
               return_value=mock_media(91)):
        with pytest.raises(ValueError, match="shorter"):
            prepare(source, target)
    assert not target.exists()


def test_video_outside_project_temp_destination_is_rejected(qa_workspace):
    source = qa_workspace / "input.mp4"
    source.write_bytes(b"source")
    with pytest.raises(ValueError, match="project/temp"):
        prepare(source, config.ROOT / "data" / "unapproved-out")
    assert source.read_bytes() == b"source"


def test_start_offset_must_be_finite_and_fit_episode(qa_workspace):
    source = qa_workspace / "episode.mp4"
    source.write_bytes(b"source")
    with pytest.raises(ValueError, match="non-negative"):
        prepare(source, qa_workspace / "prep", start_seconds=-3)
    with patch("scripts.prepare_real_test_video.probe_media",
               return_value=mock_media(240)):
        with pytest.raises(ValueError, match="full 180"):
            prepare(source, qa_workspace / "prep", start_seconds=100)
