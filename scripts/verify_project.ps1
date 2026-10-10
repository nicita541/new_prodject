param([switch]$Quick, [switch]$Full, [switch]$Video, [switch]$NoUpload, [switch]$RequireRealModel, [switch]$FastLocalStory, [switch]$FlashStory, [double]$StartSeconds = 0, [string]$PythonExe, [string]$RealSource, [string]$RealTranscript)

if (@($Quick, $Full, $Video) | Where-Object { $_ } | Select-Object -Skip 1) {
    throw 'Choose only one mode: -Quick, -Full, or -Video.'
}

if (($FastLocalStory -or $FlashStory) -and -not $RequireRealModel) {
    throw 'Experimental story modes require -RequireRealModel for a full 180s production acceptance.'
}
if ($FastLocalStory -and $FlashStory) {
    throw 'Choose only one experimental story provider.'
}
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $root
$env:PYTHONUTF8 = "1"
$env:TEMP = Join-Path $root "temp"
$env:TMP = $env:TEMP
$env:TMPDIR = $env:TEMP
$env:PYTHONPYCACHEPREFIX = Join-Path $root "cache\test-pycache"
$env:PIP_CACHE_DIR = Join-Path $root "cache\test-pip"
New-Item -ItemType Directory -Force -Path (Join-Path $root "temp"), (Join-Path $root "cache") | Out-Null

$runId = (Get-Date).ToUniversalTime().ToString("yyyyMMdd_HHmmss") + "_" + [Guid]::NewGuid().ToString("N").Substring(0, 8)
$localDir = Join-Path $root ("temp\verification-reports\" + $runId)
$logsDir = Join-Path (Join-Path $root 'logs\tests') $runId
# Reports and execution logs use different isolated directories. Both must
# exist before tests start, not just logs: checks.json is written at the end.
New-Item -ItemType Directory -Force -Path $localDir, $logsDir -ErrorAction Stop | Out-Null
$script:checks = @()
# A monotonic timer measures process durations independently of progress text.
# Overall time includes setup and media selection but excludes the later
# report push itself (which cannot know its own completion time before push).
$script:verificationStarted = [System.Diagnostics.Stopwatch]::StartNew()
# The complete real-AI acceptance (Python, React, offline E2E, ASR/VLM, render)
# has one shared 2200-second (36m40s) deadline. No individual stage may
# reset this clock; TIMEOUT remains FAIL and does not mean a successful render.
$script:verificationBudgetSeconds = 2200
$script:verificationDeadline = $null

function Add-Check([string]$Name, [string]$Status, [int]$ExitCode, [string]$Note, [double]$ElapsedSeconds = -1) {
    $measured = if ($ElapsedSeconds -ge 0) { [Math]::Round($ElapsedSeconds, 3) } else { $null }
    $script:checks += [pscustomobject]@{ name = $Name; status = $Status; exit_code = $ExitCode; note = $Note; elapsed_seconds = $measured }
    Write-Host ("[{0}] {1} {2}" -f $Status, $Name, $Note)
}

function Run-Check([string]$Name, [string]$Exe, [string[]]$Arguments, [string]$Working = $root, [int]$Timeout = 1200) {
    $stageTimer = [System.Diagnostics.Stopwatch]::StartNew()
    $outFile = Join-Path $logsDir ($Name + ".out.txt")
    $errFile = Join-Path $logsDir ($Name + ".err.txt")
    $effectiveTimeout = $Timeout
    if ($script:verificationDeadline) {
        $remaining = [int][Math]::Floor(($script:verificationDeadline - (Get-Date)).TotalSeconds)
        if ($remaining -le 0) {
            Add-Check $Name "TIMEOUT" 124 "Shared 2200-second full-AI test budget exhausted" $stageTimer.Elapsed.TotalSeconds
            return
        }
        $effectiveTimeout = [Math]::Min($Timeout, $remaining)
    }
    Write-Host ("RUN: " + $Name + " (limit " + $effectiveTimeout + "s)")
    try {
        $safeArgs = @($Arguments | ForEach-Object {
            if ($_ -match '"') { throw "Unescaped quote in test argument" }
            if ($_ -match '\s') { '"' + $_ + '"' } else { $_ }
        })
        $process = Start-Process -FilePath $Exe -ArgumentList $safeArgs -WorkingDirectory $Working -PassThru -NoNewWindow -RedirectStandardOutput $outFile -RedirectStandardError $errFile
        $elapsed = 0
        while (-not $process.WaitForExit(3000)) {
            $elapsed += 3
            if (($elapsed % 15) -eq 0) {
                $bytes = if (Test-Path -LiteralPath $outFile) { (Get-Item $outFile).Length } else { 0 }
                Write-Host ("[{0}] {1}s elapsed, stdout={2} bytes (limit {3}s)" -f $Name,$elapsed,$bytes,$effectiveTimeout)
            }
            if ($elapsed -ge $effectiveTimeout) {
                # On Windows kill the entire child process tree, not just npm
                # or pytest parent; otherwise detached workers survive forever.
                if ($IsWindows -or $env:OS -eq 'Windows_NT') {
                    & taskkill.exe /PID $process.Id /T /F 2>$null | Out-Null
                } else { try { $process.Kill() } catch { } }
                Add-Check $Name "TIMEOUT" 124 ("exceeded " + $effectiveTimeout + " seconds; inspect local diagnostics") $stageTimer.Elapsed.TotalSeconds
                return
            }
        }
        $process.Refresh()
        if (-not $process.HasExited) { throw "Process did not exit after WaitForExit" }
        $code = [int]$process.ExitCode
        $note = if ($code -eq 0) { "" } else { "exit=" + $code }

        # Never trust just the process exit code for test suites: certain
        # Windows launchers/hosts can report success despite collection
        # errors. Validate the actual pytest summary as a second signal.
        if ($Name -eq "python_tests") {
            $outputText = Get-Content -LiteralPath $outFile -Raw -ErrorAction Stop
            $hasTests = $outputText -match '(?m)\b[1-9][0-9]* passed\b'
            $hasErrors = $outputText -match '(?im)(ERROR collecting|^ERROR\s+tests[/\\]|^FAILED\s+tests[/\\]|^=+\s*(ERRORS|FAILURES)\s*=+|^no tests ran)'
            if (-not $hasTests -or $hasErrors) {
                $code = 1
                $note = "Pytest did not finish successfully; check python_tests.out.txt"
            } elseif ($code -eq 0 -and $outputText -match '(?m)\b([1-9][0-9]* passed)\b') {
                $note = $Matches[1]
            }
        }
        if ($Name -eq "react_lint" -and $code -eq 0) {
            $outputText = Get-Content -LiteralPath $outFile -Raw -ErrorAction Stop
            if ($outputText -match 'Found (\d+) warnings and 0 errors') {
                $note = "$($Matches[1]) warnings, 0 errors"
            }
        }
        # Windows Start-Process can sometimes expose a stale/incorrect exit
        # code for a child Python process. The authoritative E2E result is
        # its own freshly written report.json inside THIS run directory.
        # A missing/corrupt/failed artifact must never become a green report.
        if ($Name -in @("full_pipeline_3min", "real_model_3min")) {
            $e2eArtifact = Join-Path (Join-Path $localDir $Name) "report.json"
            try {
                if (-not (Test-Path -LiteralPath $e2eArtifact -PathType Leaf)) {
                    throw "missing report.json"
                }
                $e2e = Get-Content -LiteralPath $e2eArtifact -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($e2e.status -ne "passed") {
                    throw ("report status " + [string]$e2e.status)
                }
                $acceptedSteps = @($e2e.checks | Where-Object { $_.status -eq "passed" })
                $badSteps = @($e2e.checks | Where-Object { $_.status -ne "passed" })
                if ($acceptedSteps.Count -eq 0 -or $badSteps.Count -ne 0) {
                    throw "missing or unsuccessful E2E stages"
                }
                if ($Name -eq "real_model_3min") {
                    if ($e2e.analysis_mode -ne "real_local_whisper_and_vision") {
                        throw "real ASR and vision were not both exercised"
                    }
                    if (-not ($e2e.real_model_requests -gt 0)) {
                        throw "no confirmed local model requests"
                    }
                    if ($e2e.real_resume.model_requests_unchanged -ne $true -or
                        $e2e.real_resume.all_render_parts_cached -ne $true -or
                        $e2e.real_resume.identical_output_hashes -ne $true) {
                        throw "real-model resume and export check incomplete"
                    }
                }
            } catch {
                $code = 1
                # Don't print local report contents, model prompts, source
                # dialogue or arbitrary exception paths into public checks.
                $note = "E2E artifact validation failed; inspect local report.json"
            }
        }
        if ($code -eq 0) { Add-Check $Name "PASS" $code $note $stageTimer.Elapsed.TotalSeconds }
        else { Add-Check $Name "FAIL" $code $note $stageTimer.Elapsed.TotalSeconds }
        $process.Dispose()
    } catch {
        Set-Content -LiteralPath $errFile -Value $_.Exception.Message -Encoding UTF8
        Add-Check $Name "FAIL" 1 "could not start" $stageTimer.Elapsed.TotalSeconds
    }
}

$git = Get-Command git.exe -ErrorAction SilentlyContinue
$branch = "unknown"
$commit = "unknown"
if ($git) {
    $branch = (& git.exe -C $root branch --show-current 2>$null | Select-Object -First 1)
    $commit = (& git.exe -C $root rev-parse HEAD 2>$null | Select-Object -First 1)
}
$python = Join-Path $root "tools\python\python.exe"
$virtualPython = Join-Path $root ".venv\Scripts\python.exe"
if ($PythonExe) {
    if (-not (Test-Path -LiteralPath $PythonExe)) { throw "Python executable not found: $PythonExe" }
    $python = (Resolve-Path -LiteralPath $PythonExe).Path
} elseif (Test-Path -LiteralPath $virtualPython) {
    # Prefer isolated dependencies to avoid touching the running worktree.
    $python = $virtualPython
} elseif (-not (Test-Path -LiteralPath $python) -and $Quick -and $git) {
    # Git worktrees have separate tracked files, but a portable interpreter
    # installed in the original worktree can safely run read-only tests here.
    $worktrees = @(& git.exe -C $root worktree list --porcelain 2>$null)
    foreach ($line in $worktrees) {
        if (-not $line.StartsWith("worktree ")) { continue }
        $otherRoot = $line.Substring(9).Trim()
        if ($otherRoot -eq $root) { continue }
        $candidate = Join-Path $otherRoot "tools\python\python.exe"
        if (Test-Path -LiteralPath $candidate) {
            $python = $candidate
            break
        }
    }
}
if (-not (Test-Path -LiteralPath $python)) {
    $found = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($found) { $python = $found.Source } else { $python = $null }
}
$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
$frontend = Join-Path $root "frontend"
$ffmpeg = Join-Path $root "tools\ffmpeg\bin\ffmpeg.exe"
$ffprobe = Join-Path $root "tools\ffmpeg\bin\ffprobe.exe"

# The full-model BAT opens a chooser instead of requiring the user to type a
# 180-second file path. A cancellation is a failed acceptance test, never PASS.
$realSelectionError = ""
if ($RequireRealModel -and -not $RealSource) {
    if ($env:KADR_NONINTERACTIVE -eq "1" -or $env:CI -eq "true") {
        $realSelectionError = "Real-model mode requires -RealSource in noninteractive mode"
    } else {
        try {
            Add-Type -AssemblyName System.Windows.Forms
            $picker = New-Object System.Windows.Forms.OpenFileDialog
            $picker.Title = "Select a story video for the FULL local ASR/VLM test"
            $picker.Filter = "Videos (*.mp4;*.mkv;*.mov;*.webm)|*.mp4;*.mkv;*.mov;*.webm|All files (*.*)|*.*"
            $picker.Multiselect = $false
            $picker.CheckFileExists = $true
            $initial = Join-Path $root "data\imports"
            if (Test-Path -LiteralPath $initial) { $picker.InitialDirectory = $initial }
            try {
                if ($picker.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
                    $RealSource = $picker.FileName
                } else {
                    $realSelectionError = "Real-model verification cancelled: no story video selected"
                }
            } finally { $picker.Dispose() }
        } catch {
            $realSelectionError = "Cannot select story video: " + $_.Exception.GetType().Name
        }
    }
}
if ($StartSeconds -lt 0) { throw "StartSeconds cannot be negative" }
if ($RequireRealModel -or $RealSource) {
    $script:verificationDeadline = (Get-Date).AddSeconds($script:verificationBudgetSeconds)
    Write-Host ("FULL AI TEST DEADLINE: " + $script:verificationBudgetSeconds + " seconds (36m40s) for ALL stages combined; TIMEOUT is FAIL.")
    if ($FastLocalStory) { Write-Host "EXPERIMENTAL: 4B local story selection, no DeepSeek API; strict quality gate stays enabled." }
    if ($FlashStory) { Write-Host "PAID EXPERIMENT: local visual 4B and DeepSeek Flash story; maximum 8 new HTTP attempts per job. Some source frames are sent to DeepSeek. Strict quality gate stays enabled." }
}

Write-Host ("Run: " + $runId)
Write-Host ("Branch: " + $branch)
Write-Host ("Commit: " + $commit)
Write-Host ("Mode: " + $(if ($Quick) { "quick (no 180s E2E)" } elseif ($Video) { "video + 180s E2E" } else { "FULL: all Python/React checks + 180s E2E" }))
if ($RequireRealModel -or $RealSource) { Write-Host "FULL ACCEPTANCE: 180s real local ASR/VLM run required in addition to technical E2E." }
else { Write-Host "TECHNICAL ONLY: local ASR/VLM will not run (clearly marked in report)." }
if ($branch -notin @("codex/dramatic-montage", "fix/montage-stability")) {
    Write-Warning "Tests are running on branch '$branch', not codex/dramatic-montage. Report will record the actual commit."
}

if ($python) {
    Run-Check "python_compile" $python @("-m", "compileall", "-q", "app", "scripts", "tests") $root 180
    Run-Check "python_dependencies" $python @("-c", "__import__('fastapi');__import__('starlette');__import__('httpx');__import__('pytest');__import__('multipart');__import__('PIL')") $root 30
    $dependenciesReady = @($script:checks | Where-Object { $_.name -eq "python_dependencies" -and $_.status -eq "PASS" }).Count -eq 1
    if (-not $dependenciesReady) {
        Add-Check "python_tests" "SKIP" 0 "Required Python packages missing; create .venv and install requirements"
    } elseif ($Quick) {
        # Strictly no FFmpeg renders, even if the video tools are installed.
        Run-Check "python_tests" $python @("-m", "pytest", "-q",
            "tests/test_music.py::ConfigTests",
            "tests/test_music.py::TrackTests",
            "tests/test_music.py::SettingsPersistenceTests",
            "tests/test_music.py::RenderCacheTests",
            "tests/test_music.py::BackgroundMusicFilterTests",
            "tests/test_music.py::MusicApiTests",
            "tests/test_jobs.py", "tests/test_server_routing.py",
            "tests/test_finishing.py", "tests/test_recovery_tokens.py",
            "tests/test_scene_detection.py") $root 600
    } elseif ($Video) {
        if ((Test-Path -LiteralPath $ffmpeg) -and (Test-Path -LiteralPath $ffprobe)) {
            # Synthetic 2-second color/sine source. No user episode or AI model.
            Run-Check "python_tests" $python @("-m", "pytest", "-q",
                "tests/test_music.py::BackgroundMusicIntegrationTests") $root 600
        } else {
            Add-Check "python_tests" "SKIP" 0 "Video mode requires portable FFmpeg and FFprobe inside this worktree"
        }
    } else {
        # Double-click defaults to ALL tests, not the historical 4-file subset.
        # -Full stays as an explicit alias for the same comprehensive mode.
        Run-Check "python_tests" $python @("-m", "pytest", "-q", "tests") $root 7200
    }
} else {
    Add-Check "python_compile" "SKIP" 0 "Python unavailable"
    Add-Check "python_dependencies" "SKIP" 0 "Python unavailable"
    Add-Check "python_tests" "SKIP" 0 "Python unavailable"
}

if ($npm -and (Test-Path -LiteralPath (Join-Path $frontend "node_modules"))) {
    Run-Check "react_tests" $npm.Source @("test") $frontend 1800
    Run-Check "react_lint" $npm.Source @("run", "lint") $frontend 600
    Run-Check "react_build" $npm.Source @("run", "build") $frontend 900
} else {
    Add-Check "react_tests" "SKIP" 0 "npm/node_modules missing; run npm ci in frontend"
    Add-Check "react_lint" "SKIP" 0 "npm/node_modules missing"
    Add-Check "react_build" "SKIP" 0 "npm/node_modules missing"
}
if (Test-Path -LiteralPath $ffmpeg) {
    Run-Check "ffmpeg" $ffmpeg @("-version") $root 30
} else { Add-Check "ffmpeg" "SKIP" 0 "portable FFmpeg missing" }
if (Test-Path -LiteralPath $ffprobe) {
    Run-Check "ffprobe" $ffprobe @("-version") $root 30
} else { Add-Check "ffprobe" "SKIP" 0 "portable FFprobe missing" }

# The 180-second end-to-end test is a real decode/plan/FFmpeg/subtitle/music/
# cache/corruption-recovery/finishing/HTTP delivery run. It has its own
# output folder INSIDE this verification run and is not run in -Quick mode.
$e2eDir = Join-Path $localDir "full_pipeline_3min"
if (-not $Quick) {
    if (-not $python) {
        Add-Check "full_pipeline_3min" "SKIP" 0 "Python unavailable"
    } elseif (-not (Test-Path -LiteralPath $ffmpeg) -or -not (Test-Path -LiteralPath $ffprobe)) {
        Add-Check "full_pipeline_3min" "SKIP" 0 "Portable FFmpeg and FFprobe required"
    } else {
        New-Item -ItemType Directory -Force -Path $e2eDir | Out-Null
        Run-Check "full_pipeline_3min" $python @(
            "scripts/full_pipeline_3min.py", "--mode", "offline", "--directory", $e2eDir
        ) $root 3600
    }
}

# Real ASR/VLM is never simulated by the technical fixture. Missing input
# or models are a FAIL when this mode is requested; the report still uploads.
if ($RequireRealModel -and $RealTranscript) {
    # The FULL AI launcher must exercise actual ASR, not accept an injected
    # transcript that silently skips Whisper/speech recognition.
    Add-Check "real_model_3min" "FAIL" 1 "Full AI acceptance forbids -RealTranscript; real ASR is mandatory"
} elseif ($RealTranscript -and -not $RealSource) {
    Add-Check "real_model_3min" "FAIL" 1 "-RealTranscript requires -RealSource"
} elseif ($RequireRealModel -and -not $RealSource) {
    Add-Check "real_model_3min" "FAIL" 1 $realSelectionError
} elseif ($RealSource) {
    if ($Quick) {
        Add-Check "real_model_3min" "FAIL" 1 "Real-model test cannot run in -Quick mode"
    } elseif (-not $python -or -not (Test-Path -LiteralPath $ffmpeg) -or -not (Test-Path -LiteralPath $ffprobe)) {
        Add-Check "real_model_3min" "FAIL" 1 "Real-model test requires Python, FFmpeg and FFprobe"
    } elseif (-not (Test-Path -LiteralPath $RealSource -PathType Leaf)) {
        Add-Check "real_model_3min" "FAIL" 1 "The selected real video file is unavailable"
    } else {
        # A long original is NEVER modified. A 180s excerpt is created inside
        # the private report folder, and its path is excluded from publication.
        $realInput = Join-Path $localDir "input_real_180s"
        $realDir = Join-Path $localDir "real_model_3min"
        Run-Check "prepare_real_source" $python @(
            "scripts/prepare_real_test_video.py", "--source", $RealSource,
            "--directory", $realInput, "--start-seconds", $StartSeconds.ToString([System.Globalization.CultureInfo]::InvariantCulture)
        ) $root 2400
        $preparedOkay = @($script:checks | Where-Object {
            $_.name -eq "prepare_real_source" -and $_.status -eq "PASS"
        }).Count -eq 1
        if (-not $preparedOkay) {
            Add-Check "real_model_3min" "FAIL" 1 "Could not prepare a valid 180s story excerpt"
        } else {
            $preparedSource = (Get-Content -LiteralPath (Join-Path $realInput "selected-source.txt") -Raw -Encoding UTF8).Trim()
            New-Item -ItemType Directory -Force -Path $realDir | Out-Null
            $realArgs = @("scripts/full_pipeline_3min.py", "--mode", "real",
                          "--directory", $realDir, "--source", $preparedSource)
            if ($RealTranscript) { $realArgs += @("--transcript", $RealTranscript) }
            if ($FastLocalStory) { $realArgs += @("--local-provider", "local_fast_story") }
            if ($FlashStory) { $realArgs += @("--local-provider", "local_flash_story") }
            Run-Check "real_model_3min" $python $realArgs $root $script:verificationBudgetSeconds
        }
    }
}

# Produce safe structural AI diagnostics after PASS, FAIL or TIMEOUT, before
# calculating the overall result. Never copy a model's raw logs to GitHub.
if ($RequireRealModel -or $RealSource) {
    $safeAiReport = Join-Path $localDir "ai_diagnostics.json"
    if ($python) {
        try {
            & $python "scripts/export_safe_ai_diagnostics.py" "--test-dir" $localDir "--output" $safeAiReport
            if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $safeAiReport -PathType Leaf)) {
                throw "safe diagnostic extraction unavailable"
            }
            Add-Check "safe_ai_diagnostics" "PASS" 0 "allowlisted AI metadata generated"
        } catch {
            Add-Check "safe_ai_diagnostics" "FAIL" 1 "safe AI diagnostics generation failed"
        }
    } else {
        Add-Check "safe_ai_diagnostics" "SKIP" 0 "Python missing"
    }
}

# Produce a second, safe report covering every test-check and nested
# production stage. Write an interim local-only timing snapshot BEFORE the
# final checks.json, so the exporter has true per-process wall-clock timings.
# This runs for both AI and technical test profiles, even after FAIL/TIMEOUT.
$stageTimingPath = Join-Path $localDir "stage_timings.json"
$timingSnapshot = [pscustomobject]@{
    elapsed_seconds = [Math]::Round($script:verificationStarted.Elapsed.TotalSeconds, 3)
    checks = $script:checks
}
$timingSnapshot | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $localDir "timing_snapshot.local.json") -Encoding UTF8
if ($python) {
    try {
        & $python "scripts/export_stage_timings.py" "--test-dir" $localDir "--output" $stageTimingPath
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $stageTimingPath -PathType Leaf) -or
            -not (Test-Path -LiteralPath (Join-Path $localDir "stage_timings.md") -PathType Leaf)) {
            throw "stage timing export unavailable"
        }
        Add-Check "stage_timings" "PASS" 0 "full timing breakdown generated"
    } catch {
        Add-Check "stage_timings" "FAIL" 1 "stage timing export failed"
    }
} else {
    Add-Check "stage_timings" "SKIP" 0 "Python unavailable"
}

$failed = @($script:checks | Where-Object { $_.status -in @("FAIL", "TIMEOUT") }).Count
$skipped = @($script:checks | Where-Object { $_.status -eq "SKIP" }).Count
$passed = @($script:checks | Where-Object { $_.status -eq "PASS" }).Count
$overall = if ($failed -gt 0) { "FAIL" } elseif ($skipped -gt 0) { "INCOMPLETE" } else { "PASS" }
$summary = [pscustomobject]@{
    run_id = $runId
    timestamp_utc = (Get-Date).ToUniversalTime().ToString("o")
    elapsed_seconds = [Math]::Round($script:verificationStarted.Elapsed.TotalSeconds, 3)
    branch = $branch
    commit = $commit
    mode = if ($Quick) { "quick" } elseif ($Video) { "video" } else { "full" }
    run_profile = if ($RequireRealModel -or $RealSource) { "full_with_local_ai" } else { "technical_without_ai" }
    real_model_scope = if ($RequireRealModel -or $RealSource) { "required" } else { "not_run_technical_only" }
    overall = $overall
    passed = $passed
    failed = $failed
    skipped = $skipped
    checks = $script:checks
    logs_dir = $logsDir
}
if ($FastLocalStory) { $summary.run_profile = "full_with_experimental_local_4b_story" }
if ($FlashStory) { $summary.run_profile = "full_with_limited_deepseek_flash_story" }
# A test may remove temporary files while running; recreate output folders
# before writing reports so a successful test run never fails on a missing dir.
New-Item -ItemType Directory -Force -Path $localDir, $logsDir -ErrorAction Stop | Out-Null
$summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $localDir "checks.json") -Encoding UTF8

# Extract only allowlisted, non-private E2E facts; never publish raw video,
# transcript, full paths, source metadata, model prompts or actual job content.
$e2eOverview = @()
foreach ($kind in @("full_pipeline_3min", "real_model_3min")) {
    $folder = if ($kind -eq "full_pipeline_3min") { $e2eDir } else { Join-Path $localDir "real_model_3min" }
    $reportFile = Join-Path $folder "report.json"
    if (-not (Test-Path -LiteralPath $reportFile)) { continue }
    try {
        $details = Get-Content -LiteralPath $reportFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $e2eOverview += [pscustomobject]@{
            check = $kind
            status = $details.status
            analysis_mode = $details.analysis_mode
            duration_seconds = $details.duration_seconds
            cache_all_parts_reused = [bool]$details.cache.all_parts_reused
            cache_corrupt_srt_forced_rerender = [bool]$details.cache.corrupt_srt_forced_rerender
            passed_steps = @($details.checks | Where-Object { $_.status -eq "passed" }).Count
            failed_steps = @($details.checks | Where-Object { $_.status -eq "failed" }).Count
            stages = @($details.checks | ForEach-Object {
                [pscustomobject]@{ name = $_.name; status = $_.status; seconds = $_.seconds }
            })
        }
    } catch {
        Write-Warning ("Could not summarize " + $kind + ": " + $_.Exception.Message)
    }
}
# Publish allowlisted files only: summary and a truncated, redacted log tail.
$uploadDir = Join-Path $localDir "sanitized"
$uploadLogs = Join-Path $uploadDir "logs"
New-Item -ItemType Directory -Force -Path $uploadLogs | Out-Null
# Sanitize source paths from the published summary while preserving detailed
# local checks.json for support. Original media and ASR never leave this PC.
$publicSummary = $summary | ConvertTo-Json -Depth 8 | ConvertFrom-Json
$publicSummary.logs_dir = "[LOCAL_ONLY]"
$publicSummary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $uploadDir "checks.json") -Encoding UTF8
$e2eOverview | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $uploadDir "e2e_overview.json") -Encoding UTF8
# Both files are GENERATED from a strict internal stage/check name allowlist.
# Publishing raw timeline.jsonl would leak episode contents, so never do so.
foreach ($timingFile in @("stage_timings.json", "stage_timings.md")) {
    $sourceTiming = Join-Path $localDir $timingFile
    if (Test-Path -LiteralPath $sourceTiming -PathType Leaf) {
        Copy-Item -LiteralPath $sourceTiming -Destination (Join-Path $uploadDir $timingFile) -Force
    }
}
# ONLY the extractor output is publishable. Do not copy the private job folder.
$safeAiReport = Join-Path $localDir "ai_diagnostics.json"
if (Test-Path -LiteralPath $safeAiReport -PathType Leaf) {
    Copy-Item -LiteralPath $safeAiReport -Destination (Join-Path $uploadDir "ai_diagnostics.json") -Force
}
foreach ($check in $script:checks) {
    # Real ASR/VLM may print episode dialogue, frame descriptions and prompts.
    # Publish only status, error type and approved stage names for this mode;
    # leave its raw output, including excerpts, on the local computer.
    if ($check.name -in @("prepare_real_source", "real_model_3min")) { continue }
    foreach ($stream in @("out", "err")) {
        $src = Join-Path $logsDir ($check.name + "." + $stream + ".txt")
        if (-not (Test-Path -LiteralPath $src)) { continue }
        # Test runners emit UTF-8; PowerShell 5.1 otherwise reads these files
        # in the Windows code page and mangles Russian stage messages.
        $body = (Get-Content -LiteralPath $src -Tail 120 -Encoding UTF8 -ErrorAction SilentlyContinue | Out-String)
        if ($body.Length -gt 12000) { $body = $body.Substring($body.Length - 12000) }
        $body = $body -replace '(?i)(github_pat_|gh[pousr]_|sk-)[A-Za-z0-9_-]{12,}', '[REDACTED_SECRET]'
        $body = $body -replace '(?i)(authorization\s*[:=]\s*bearer\s+)\S+', '$1[REDACTED]'
        $body = $body -replace '(?i)(api[_-]?key|password|access[_-]?token|secret)\s*[:=]\s*\S+', '$1=[REDACTED]'
        $body = $body -replace '(?i)https?://[^\s/@]+:[^\s/@]+@', 'https://[REDACTED]@'
        $body = $body -replace '[A-Za-z]:\\Users\\[^\\\s]+', '[USER_HOME]'
        if ($RealSource) { $body = $body.Replace($RealSource, '[SELECTED_VIDEO]') }
        Set-Content -LiteralPath (Join-Path $uploadLogs ($check.name + "." + $stream + ".txt")) -Value $body -Encoding UTF8
    }
}
$nl = [Environment]::NewLine
$md = @("# KADR verification report", "", "- Run: $runId", "- Logs: [LOCAL_ONLY]", "- Branch: $branch", "- Commit: $commit", "- Profile: $(if ($RequireRealModel -or $RealSource) {'FULL WITH LOCAL AI'} else {'TECHNICAL WITHOUT AI'})", "- Result: $overall (passed $passed; failed $failed; skipped $skipped)", "- Real ASR/VLM: $(if ($RequireRealModel -or $RealSource) {'REQUIRED, see real_model_3min'} else {'NOT RUN (technical test)'})", "", "| Check | Result | Details |", "| --- | --- | --- |")
foreach ($check in $script:checks) { $md += "| $($check.name) | $($check.status) | $($check.note) |" }
if ($RequireRealModel -or $RealSource) {
    $md += @("", "- AI diagnostics: ai_diagnostics.json (safe numeric and stage metadata)")
}
$md += @("", "- Stage timings: stage_timings.md and stage_timings.json (safe wall-clock and nested breakdown)")
$md += @("", "Raw, unredacted logs remain on the user's computer.")
($md -join $nl) | Set-Content -LiteralPath (Join-Path $uploadDir "README.md") -Encoding UTF8
(($md -join $nl) -replace '\[LOCAL_ONLY\]', $logsDir) | Set-Content -LiteralPath (Join-Path $localDir "summary.md") -Encoding UTF8

$uploadStatus = "disabled"
if (-not $NoUpload) {
    $uploadStatus = "failed"
    if (-not $git) {
        Write-Warning "Git is unavailable; report saved locally."
    } else {
        try {
            $remote = (& git.exe -C $root remote get-url origin 2>$null | Select-Object -First 1)
            if (-not $remote) { throw "Git origin not configured" }
            $publisher = Join-Path $localDir "publisher"
            New-Item -ItemType Directory -Force -Path $publisher | Out-Null
            & git.exe -C $publisher init -q
            & git.exe -C $publisher config user.name "Montage test reporter"
            & git.exe -C $publisher config user.email "montage-test-reporter@users.noreply.github.com"
            & git.exe -C $publisher remote add origin $remote
            # Separate temporary repository: no change to the working code tree.
            $previousPreference = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            & git.exe -C $publisher fetch -q --depth 1 origin "refs/heads/test-reports" 2>$null
            $fetchCode = $LASTEXITCODE
            $ErrorActionPreference = $previousPreference
            if ($fetchCode -eq 0) {
                & git.exe -C $publisher checkout -q -B test-reports FETCH_HEAD
            } else {
                & git.exe -C $publisher checkout -q --orphan test-reports
            }
            if ($LASTEXITCODE -ne 0) { throw "Cannot initialize report branch" }
            New-Item -ItemType Directory -Force -Path (Join-Path $publisher "runs") | Out-Null
            $target = Join-Path $publisher ("runs\" + $runId)
            Copy-Item -LiteralPath $uploadDir -Destination $target -Recurse
            & git.exe -C $publisher add -- ("runs/" + $runId)
            if ($LASTEXITCODE -ne 0) { throw "Cannot stage report" }
            & git.exe -C $publisher commit -q -m ("test-report: " + $runId + " " + $overall)
            if ($LASTEXITCODE -ne 0) { throw "Cannot commit report" }
            & git.exe -C $publisher push -q origin "HEAD:refs/heads/test-reports"
            if ($LASTEXITCODE -ne 0) { throw "Push rejected or authentication unavailable" }
            $uploadStatus = "success"
            Write-Host ("Published to test-reports/runs/" + $runId)
        } catch {
            Write-Warning ("Upload failed: " + $_.Exception.Message)
        }
    }
}
Write-Host ("Overall: " + $overall)
Write-Host ("Local report: " + (Join-Path $localDir "summary.md"))
Write-Host ("GitHub upload: " + $uploadStatus)
if ($failed -gt 0) { exit 1 }
if ($skipped -gt 0) { exit 2 }
if ($uploadStatus -eq "failed") { exit 3 }
exit 0
