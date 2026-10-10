"""Regression contract: local verification reports must have their own directory.

GitHub Actions Linux does not execute Windows PowerShell, so this test covers
the previous Windows-only missing-directory failure without pretending to run
PowerShell itself.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_report_directory_created_before_checks_json_is_written():
    script = (ROOT / "scripts" / "verify_project.ps1").read_text("utf-8")
    declaration = script.index("$localDir = Join-Path")
    create = re.search(
        r"New-Item\s+-ItemType\s+Directory\s+-Force\s+-Path\s+\$localDir\s*,\s*\$logsDir",
        script[declaration:],
    )
    assert create is not None, "verify_project.ps1 must create both run folders"
    first_write = script.index('Join-Path $localDir "checks.json"')
    assert declaration + create.start() < first_write, "report folder created too late"
    assert script.count('New-Item -ItemType Directory -Force -Path $localDir, $logsDir') >= 2


def test_publish_is_from_isolated_temporary_git_repo_to_reports_only():
    script = (ROOT / "scripts" / "verify_project.ps1").read_text("utf-8")
    assert 'Join-Path $localDir "publisher"' in script
    assert '& git.exe -C $publisher init' in script
    assert 'HEAD:refs/heads/test-reports' in script
    assert 'Copy-Item -LiteralPath $uploadDir -Destination $target -Recurse' in script
    assert '"logs_dir = $logsDir"' not in script  # reports contain sanitized files only


def test_default_verification_runs_full_python_suite_and_real_180s_video_pipeline():
    script = (ROOT / "scripts" / "verify_project.ps1").read_text("utf-8")
    # The short four-file Python suite must not remain the default.
    assert 'Run-Check "python_tests" $python @("-m", "pytest", "-q", "tests")' in script
    assert 'tests/test_music.py", "tests/test_media.py", "tests/test_api.py", "tests/test_jobs.py' not in script
    # The full media pipeline must run for normal double-click and -Full.
    assert 'if (-not $Quick) {' in script
    assert 'Run-Check "full_pipeline_3min" $python @(' in script
    assert '"scripts/full_pipeline_3min.py", "--mode", "offline", "--directory", $e2eDir' in script
    assert '$e2eDir = Join-Path $localDir "full_pipeline_3min"' in script
    assert 'Run-Check "real_model_3min" $python $realArgs' in script
    assert 'if ($RealTranscript -and -not $RealSource)' in script
    assert '"--mode", "real"' in script
    assert 'real_model_scope = if ($RealSource)' in script


def test_full_pipeline_result_is_in_unified_report_and_sanitized_publication():
    script = (ROOT / "scripts" / "verify_project.ps1").read_text("utf-8")
    assert 'Join-Path $folder "report.json"' in script
    assert 'e2e_overview.json' in script
    assert 'cache_corrupt_srt_forced_rerender' in script
    assert '$uploadDir = Join-Path $localDir "sanitized"' in script
    assert '"HEAD:refs/heads/test-reports"' in script
    assert '-NoUpload' not in script  # actual option is the switch name without hyphen
    assert 'if (-not $NoUpload)' in script
