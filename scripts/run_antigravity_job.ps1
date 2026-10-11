param(
    [Parameter(Mandatory=$true)][string]$JobDirectory,
    [string]$AgyExe,
    [string]$Model = 'gemini-3.8-flash-low',
    [ValidateRange(1,180)][int]$MaxMinutes = 30
)
# User-started direct scripting. No HTTP control of KADR, no credential access.
$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$job = (Resolve-Path -LiteralPath $JobDirectory).Path
if (-not $job.StartsWith($workspace + '\', [StringComparison]::OrdinalIgnoreCase) -or
    -not (Test-Path -LiteralPath (Join-Path $job 'job.json'))) { throw 'Job must be inside workspace' }
$root = Join-Path $job 'antigravity'
New-Item -ItemType Directory -Force -Path $root | Out-Null
if (-not (Resolve-Path -LiteralPath $root).Path.StartsWith($job + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Exchange folder must be inside job'
}
$env:TEMP = Join-Path $workspace 'temp'
$env:TMP = $env:TEMP
$env:TMPDIR = $env:TEMP
$lock = [IO.File]::Open((Join-Path $root 'runner.lock'), [IO.FileMode]::OpenOrCreate,
    [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
$timer = [Diagnostics.Stopwatch]::StartNew()
$packetId = $null
function Write-Runner([string]$Status, [string]$Detail) {
    $path = Join-Path $root 'runner.json'
    $temporary = $path + '.pending'
    $value = @{status=$Status;packet=$packetId;message=$Detail;model=$Model;
        wall_seconds=$timer.Elapsed.TotalSeconds;updated_at=(Get-Date).ToUniversalTime().ToString('o')}
    [IO.File]::WriteAllText($temporary, ($value | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
    if (Test-Path -LiteralPath $path) { [IO.File]::Replace($temporary, $path, [NullString]::Value) }
    else { [IO.File]::Move($temporary, $path) }
}
try {
    Write-Runner 'waiting' 'User-started script waiting for current packet'
    Write-Host 'Keep this separate script running. Cancel in KADR stops the current CLI request.'
    while ($timer.Elapsed.TotalMinutes -lt $MaxMinutes) {
        $state = Get-Content -LiteralPath (Join-Path $job 'job.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($state.analysis_provider -ne 'antigravity_manual') { throw 'Job no longer uses Antigravity' }
        if ($state.status -eq 'completed') { Write-Runner 'completed' 'KADR finished'; return }
        if ($state.status -in @('failed','cancelled','interrupted','waiting_analysis') -or
            (Test-Path -LiteralPath (Join-Path $job '.cancel'))) {
            Write-Runner 'stopped' 'Job stopped; start/retry in KADR before running this script again'; return
        }
        $automation = Get-Content -LiteralPath (Join-Path $root 'automation.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $automation.enabled) { throw 'Enable automatic file reception in KADR first' }
        $exchangePath = Join-Path $root 'exchange.json'
        if (Test-Path -LiteralPath $exchangePath) {
            $exchange = Get-Content -LiteralPath $exchangePath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($exchange.status -eq 'error') { throw 'KADR rejected the result; inspect packet before retry' }
            if ($exchange.status -eq 'waiting' -and $exchange.packet -match '^[a-f0-9]{64}$') {
                $packetId = $exchange.packet
                $packet = Join-Path $root ('packets\' + $packetId)
                if (-not (Resolve-Path -LiteralPath $packet).Path.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) {
                    throw 'Packet outside exchange folder'
                }
                if (-not (Test-Path -LiteralPath (Join-Path $packet 'agy-result.json')) -and
                    -not (Test-Path -LiteralPath (Join-Path $packet 'result.json'))) {
                    Write-Runner 'processing' 'Running official CLI for current packet'
                    $remaining = [Math]::Max(1, [Math]::Min(240, [int][Math]::Floor($MaxMinutes * 60 - $timer.Elapsed.TotalSeconds)))
                    & (Join-Path $PSScriptRoot 'run_antigravity_packet.ps1') -PacketDirectory $packet -AgyExe $AgyExe -Model $Model -StopFile (Join-Path $job '.cancel') -TimeLimitSeconds $remaining
                    Write-Runner 'waiting' 'Result published; waiting for validation and next packet'
                }
            }
        }
        Start-Sleep -Milliseconds 500
    }
    throw 'Standalone script reached its time budget; checkpoints retained'
} catch {
    Write-Runner 'error' $_.Exception.Message
    throw
} finally {
    $lock.Dispose()
}
