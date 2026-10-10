param([string]$RunId = "")

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$reports = Join-Path $root "temp\verification-reports"
if (-not (Test-Path -LiteralPath $reports -PathType Container)) {
    throw "No previous verification reports on this computer."
}
if ($RunId -and $RunId -notmatch '^\d{8}_\d{6}_[a-fA-F0-9]{8}$') {
    throw "Invalid run ID."
}
if ($RunId) {
    $run = Get-Item -LiteralPath (Join-Path $reports $RunId) -ErrorAction Stop
} else {
    $run = Get-ChildItem -LiteralPath $reports -Directory |
        Where-Object { $_.Name -match '^\d{8}_\d{6}_[a-fA-F0-9]{8}$' -and
                      (Test-Path -LiteralPath (Join-Path $_.FullName 'real_model_3min')) } |
        Sort-Object Name -Descending | Select-Object -First 1
}
if (-not $run) { throw "No previous real-model run found." }
if (-not (Test-Path -LiteralPath (Join-Path $run.FullName 'real_model_3min'))) {
    throw "Selected run has no real-model artifacts."
}
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = Join-Path $root "tools\python\python.exe"
}
if (-not (Test-Path -LiteralPath $python)) {
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $command) { throw "Python unavailable." }
    $python = $command.Source
}
$git = Get-Command git.exe -ErrorAction Stop
$remote = (& $git.Source -C $root remote get-url origin 2>$null | Select-Object -First 1)
if (-not $remote) { throw "Git origin is not configured." }

$diagnostics = Join-Path $run.FullName "ai_diagnostics.json"
& $python (Join-Path $root "scripts\export_safe_ai_diagnostics.py") "--test-dir" $run.FullName "--output" $diagnostics
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $diagnostics)) {
    throw "Safe diagnostics export failed."
}
Write-Host ("Prepared safe AI diagnostics for run " + $run.Name)

$published = $false
for ($attempt = 1; $attempt -le 3 -and -not $published; $attempt++) {
    $publisher = Join-Path (Join-Path $root "temp") ("ai-diagnostics-publisher-" + [guid]::NewGuid().ToString("N"))
    try {
        New-Item -ItemType Directory -Path $publisher -Force | Out-Null
        & $git.Source -C $publisher init -q
        & $git.Source -C $publisher config user.name "Montage test reporter"
        & $git.Source -C $publisher config user.email "montage-test-reporter@users.noreply.github.com"
        & $git.Source -C $publisher remote add origin $remote
        & $git.Source -C $publisher fetch -q --depth 1 origin "refs/heads/test-reports"
        if ($LASTEXITCODE -ne 0) { throw "Cannot fetch test-reports" }
        & $git.Source -C $publisher checkout -q -B test-reports FETCH_HEAD
        if ($LASTEXITCODE -ne 0) { throw "Cannot checkout test-reports" }
        $target = Join-Path (Join-Path $publisher "runs") $run.Name
        New-Item -ItemType Directory -Path $target -Force | Out-Null
        Copy-Item -LiteralPath $diagnostics -Destination (Join-Path $target "ai_diagnostics.json") -Force
        $relative = "runs/" + $run.Name + "/ai_diagnostics.json"
        & $git.Source -C $publisher add -- $relative
        & $git.Source -C $publisher diff --cached --quiet
        if ($LASTEXITCODE -eq 0) {
            Write-Host "The safe AI diagnostics are already published."
            $published = $true
            break
        }
        & $git.Source -C $publisher commit -q -m ("test-report: backfill safe AI diagnostics " + $run.Name)
        if ($LASTEXITCODE -ne 0) { throw "Cannot commit safe diagnostics" }
        & $git.Source -C $publisher push -q origin "HEAD:refs/heads/test-reports"
        if ($LASTEXITCODE -eq 0) { $published = $true }
    } finally {
        if (Test-Path -LiteralPath $publisher) {
            Remove-Item -LiteralPath $publisher -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
if (-not $published) {
    throw "Could not publish safe AI diagnostics after three attempts."
}
Write-Host ("DONE: open https://github.com/nicita541/new_prodject/tree/test-reports/runs/" + $run.Name)
