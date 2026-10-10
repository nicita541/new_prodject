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
