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
    assert 'real_model_scope = if ($RequireRealModel -or $RealSource)' in script
    assert 'run_profile = if ($RequireRealModel -or $RealSource)' in script


def test_full_pipeline_result_is_in_unified_report_and_sanitized_publication():
    script = (ROOT / "scripts" / "verify_project.ps1").read_text("utf-8")
    assert 'Join-Path $folder "report.json"' in script
    assert 'e2e_overview.json' in script
    assert 'cache_corrupt_srt_forced_rerender' in script
    assert '$uploadDir = Join-Path $localDir "sanitized"' in script
    assert '"HEAD:refs/heads/test-reports"' in script
    assert '-NoUpload' not in script  # actual option is the switch name without hyphen
    assert 'if (-not $NoUpload)' in script


def test_published_logs_decode_utf8_to_preserve_russian_diagnostics():
    script = (ROOT / "scripts" / "verify_project.ps1").read_text("utf-8")
    assert "Get-Content -LiteralPath $src -Tail 120 -Encoding UTF8" in script


def test_user_friendly_test_folder_has_three_distinct_auto_publishing_launchers():
    folder = ROOT / "ТЕСТЫ"
    technical = (folder / "1_ПРОВЕРКА_БЕЗ_ИИ.bat").read_text("utf-8")
    full = (folder / "2_ПОЛНАЯ_ПРОВЕРКА_С_ИИ.bat").read_text("utf-8")
    cloud = (folder / "3_ПОЛНАЯ_ПРОВЕРКА_DEEPSEEK.bat").read_text("utf-8")
    assert sorted(path.name for path in folder.glob("*.bat")) == [
        "1_ПРОВЕРКА_БЕЗ_ИИ.bat",
        "2_ПОЛНАЯ_ПРОВЕРКА_С_ИИ.bat",
        "3_ПОЛНАЯ_ПРОВЕРКА_DEEPSEEK.bat",
    ]
    assert not (ROOT / "ПРОВЕРИТЬ_ПРОЕКТ.bat").exists()
    assert not (ROOT / "test_full_pipeline_3min.bat").exists()
    for bat in (technical, full, cloud):
        assert "powershell.exe -NoProfile -STA -ExecutionPolicy Bypass" in bat
        assert 'if not "%KADR_NONINTERACTIVE%"=="1" pause' in bat
        assert "exit /b %RESULT%" in bat
        assert "-NoUpload" not in bat
        assert "scripts\\verify_project.ps1" in bat
    assert "-RequireRealModel" not in technical
    assert "-RequireRealModel" in full
    assert "-FlashStory" not in full
    assert "-RequireRealModel -FlashStory" in cloud


def test_required_real_model_cannot_silently_pass_or_publish_source_media():
    script = (ROOT / "scripts" / "verify_project.ps1").read_text("utf-8")
    assert "[switch]$RequireRealModel" in script
    assert "System.Windows.Forms.OpenFileDialog" in script
    assert 'Add-Check "real_model_3min" "FAIL"' in script
    assert 'Run-Check "prepare_real_source"' in script
    assert 'Run-Check "real_model_3min" $python $realArgs' in script
    assert 'run_profile = if ($RequireRealModel -or $RealSource)' in script
    assert 'HEAD:refs/heads/test-reports' in script
    assert '$publicSummary.logs_dir = "[LOCAL_ONLY]"' in script
    assert '"[SELECTED_VIDEO]"' not in script
    assert "'[SELECTED_VIDEO]'" in script


def test_required_full_ai_cannot_bypass_actual_asr_using_supplied_transcript():
    script = (ROOT / "scripts" / "verify_project.ps1").read_text("utf-8")
    assert 'if ($RequireRealModel -and $RealTranscript)' in script
    assert 'Full AI acceptance forbids -RealTranscript' in script
    assert 'Add-Check "real_model_3min" "FAIL"' in script


def test_reports_do_not_publish_raw_real_model_or_selected_video_logs():
    script = (ROOT / "scripts" / "verify_project.ps1").read_text("utf-8")
    assert 'if ($check.name -in @("prepare_real_source", "real_model_3min")) { continue }' in script
    assert 'Add-Check $Name "TIMEOUT" 124 ("exceeded " + $effectiveTimeout + " seconds; inspect local diagnostics")' in script
    assert '$publicSummary.logs_dir = "[LOCAL_ONLY]"' in script


def test_real_ai_run_has_one_1800_second_budget_across_all_checks():
    script = (ROOT / "scripts" / "verify_project.ps1").read_text("utf-8")
    assert '$script:verificationBudgetSeconds = 1800' in script
    assert '$script:verificationDeadline = (Get-Date).AddSeconds($script:verificationBudgetSeconds)' in script
    assert '$remaining = [int][Math]::Floor(($script:verificationDeadline - (Get-Date)).TotalSeconds)' in script
    assert '$effectiveTimeout = [Math]::Min($Timeout, $remaining)' in script
    assert 'Run-Check "real_model_3min" $python $realArgs $root $script:verificationBudgetSeconds' in script
    assert 'Shared 1800-second full-AI test budget exhausted' in script
    assert 'TIMEOUT is FAIL' in script
    assert '21600' not in script


def test_windows_launcher_rejects_false_green_e2e_artifacts():
    script = (ROOT / "scripts" / "verify_project.ps1").read_text("utf-8")
    # Regression: one published run had real_model_3min PASS in checks.json
    # but failed in e2e_overview.json after 540 seconds. The child exit code
    # alone is insufficient on Windows.
    assert 'if ($Name -in @("full_pipeline_3min", "real_model_3min"))' in script
    assert 'Join-Path (Join-Path $localDir $Name) "report.json"' in script
    assert 'if ($e2e.status -ne "passed")' in script
    assert '$acceptedSteps.Count -eq 0 -or $badSteps.Count -ne 0' in script
    assert '$expectedAnalysisMode = if ($FlashStory -or $FlashBudgeted)' in script
    assert '"real_local_whisper_and_vision"' in script
    assert '"real_local_whisper_and_paid_deepseek_story"' in script
    assert 'if ($e2e.analysis_mode -ne $expectedAnalysisMode)' in script
    assert '$e2e.real_resume.paid_requests_unchanged -ne $true' in script
    assert '$e2e.real_model_requests -gt 0' in script
    assert '$e2e.real_resume.model_requests_unchanged -ne $true' in script
    assert '$e2e.real_resume.all_render_parts_cached -ne $true' in script
    assert '$e2e.real_resume.identical_output_hashes -ne $true' in script
    assert '$code = 1' in script
    assert 'E2E artifact validation failed; inspect local report.json' in script


def test_full_ai_auto_publishes_allowlisted_model_diagnostics_on_failure_too():
    script = (ROOT / "scripts" / "verify_project.ps1").read_text("utf-8")
    assert 'scripts/export_safe_ai_diagnostics.py' in script
    assert 'Join-Path $localDir "ai_diagnostics.json"' in script
    assert 'Copy-Item -LiteralPath $safeAiReport -Destination (Join-Path $uploadDir "ai_diagnostics.json") -Force' in script
    assert script.index('scripts/export_safe_ai_diagnostics.py') < script.index('$failed = @(')
    assert 'if ($check.name -in @("prepare_real_source", "real_model_3min")) { continue }' in script


def test_optional_log_backfill_remains_in_scripts_without_extra_launcher():
    ps = (ROOT / "scripts" / "publish_latest_ai_diagnostics.ps1").read_text("utf-8")
    assert 'scripts\\export_safe_ai_diagnostics.py' in ps
    assert 'ai_diagnostics.json' in ps
    assert 'refs/heads/test-reports' in ps
    assert '3 -and -not $published' in ps
    assert 'full_pipeline_3min.py' not in ps
    assert 'run_production_raw_quality.py' not in ps
    assert not (ROOT / "ТЕСТЫ" / "3_ОТПРАВИТЬ_ПОСЛЕДНИЕ_ЛОГИ_ИИ.bat").exists()


def test_full_verification_reports_every_step_duration_and_bottlenecks():
    script = (ROOT / "scripts" / "verify_project.ps1").read_text("utf-8")
    assert '$script:verificationStarted = [System.Diagnostics.Stopwatch]::StartNew()' in script
    assert '$stageTimer = [System.Diagnostics.Stopwatch]::StartNew()' in script
    assert '$stageTimer.Elapsed.TotalSeconds' in script
    assert 'elapsed_seconds = $measured' in script
    assert 'scripts/export_stage_timings.py' in script
    assert 'timing_snapshot.local.json' in script
    assert 'Join-Path $uploadDir $timingFile' in script
    assert '@("stage_timings.json", "stage_timings.md")' in script
    assert 'Add-Check "stage_timings" "FAIL"' in script
    assert script.index('scripts/export_stage_timings.py') < script.index('$failed = @(')


def test_backfill_generates_both_timing_files_without_replaying_models():
    script = (ROOT / "scripts" / "publish_latest_ai_diagnostics.ps1").read_text("utf-8")
    assert "scripts\\export_stage_timings.py" in script
    assert 'stage_timings.json' in script
    assert 'stage_timings.md' in script
    assert 'ai_diagnostics.json' in script
    assert 'full_pipeline_3min.py' not in script
    assert 'run_production_raw_quality.py' not in script
