param(
    [Parameter(Mandatory=$true)][string]$JobDirectory,
    [string]$AgyExe,
    [string]$Model = 'gemini-3.8-flash-low',
    [switch]$DefaultAgent,
    [ValidateRange(0,180)][int]$MaxMinutes = 0,
    [ValidateRange(1,2)][int]$MaxConcurrent = 2,
    [string]$ManagedStopFile
)
# Official CLI exchange: owned by the processing worker or explicitly user-started.
$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$job = (Resolve-Path -LiteralPath $JobDirectory).Path
if (-not $job.StartsWith($workspace + '\', [StringComparison]::OrdinalIgnoreCase) -or
    -not (Test-Path -LiteralPath (Join-Path $job 'job.json'))) { throw 'Job must be inside workspace' }
$root = Join-Path $job 'antigravity'
if ($ManagedStopFile -and
    ([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($ManagedStopFile)) -ne $root -or
     [IO.Path]::GetFileName($ManagedStopFile) -notmatch '^\.managed-stop-[a-f0-9]{32}$')) {
    throw 'Managed stop file must belong to this exchange folder'
}
New-Item -ItemType Directory -Force -Path $root | Out-Null
if (-not (Resolve-Path -LiteralPath $root).Path.StartsWith($job + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Exchange folder must be inside job'
}
$env:TEMP = Join-Path $workspace 'temp'
$env:TMP = $env:TEMP
$env:TMPDIR = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
# Atomic rename replaces content without copying destination ACL metadata.
# ReplaceFile requires additional ACL rights on some Windows installations.
if (-not ('KadrAtomicFile' -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class KadrAtomicFile {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    public static extern bool MoveFileEx(string source, string destination, int flags);
}
"@
}
function Publish-AtomicFile([string]$Source, [string]$Destination) {
    for ($publishAttempt=0; $publishAttempt -lt 20; $publishAttempt++) {
        if ([KadrAtomicFile]::MoveFileEx($Source, $Destination, 9)) { return }
        $errorCode = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
        if ($errorCode -notin @(5,32,33) -or $publishAttempt -eq 19) {
            throw (New-Object ComponentModel.Win32Exception($errorCode))
        }
        Start-Sleep -Milliseconds 50
    }
}

$lock = [IO.File]::Open((Join-Path $root 'runner.lock'), [IO.FileMode]::OpenOrCreate,
    [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
$timer = [Diagnostics.Stopwatch]::StartNew()
$packetId = $null
$workers = @{}
$launched = New-Object 'Collections.Generic.HashSet[string]'
$quotaTickets = @{}
$runnerStop = Join-Path $root ('.runner-stop-' + [Guid]::NewGuid().ToString('N'))
function Write-Runner([string]$Status, [string]$Detail) {
    $path = Join-Path $root 'runner.json'
    $temporary = $path + '.pending'
    $value = @{status=$Status;packet=$packetId;message=$Detail;model=$Model;
        wall_seconds=$timer.Elapsed.TotalSeconds;updated_at=(Get-Date).ToUniversalTime().ToString('o');
        agent_requested=$(if ($DefaultAgent) { 'default' } else { 'kadr-json' });
        active_packets=@($workers.Keys);max_concurrent=$MaxConcurrent;
        owner=$(if ($ManagedStopFile) { 'worker' } else { 'external' })}
    [IO.File]::WriteAllText($temporary, ($value | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
    Publish-AtomicFile $temporary $path
}
function Read-ExchangeJson([string]$Path) {
    # Retry transient local sharing failures only; no model call is repeated.
    for ($readAttempt=0; $readAttempt -lt 20; $readAttempt++) {
        try { return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json) }
        catch [IO.IOException], [UnauthorizedAccessException] {
            if ($readAttempt -eq 19) { throw "Cannot read exchange file after transient retries: $(Split-Path $Path -Leaf)" }
            Start-Sleep -Milliseconds 50
        }
    }
}
try {
    Write-Runner 'waiting' 'User-started script waiting for independent packets'
    Write-Host 'Keep this separate script running. Cancel in KADR stops the current CLI request.'
    # Production has no overall deadline. Tests may opt into a bounded run.
    :processing while ($MaxMinutes -eq 0 -or $timer.Elapsed.TotalMinutes -lt $MaxMinutes) {
        $state = Read-ExchangeJson (Join-Path $job 'job.json')
        if ($state.analysis_provider -ne 'antigravity_manual') { throw 'Job no longer uses Antigravity' }
        if ($state.status -eq 'completed') { Write-Runner 'completed' 'KADR finished'; return }
        if ($ManagedStopFile -and (Test-Path -LiteralPath $ManagedStopFile)) {
            Write-Runner 'stopped' 'Owned worker finished; checkpoints retained'; return
        }
        if ($state.status -in @('failed','cancelled','interrupted','waiting_analysis') -or
            (Test-Path -LiteralPath (Join-Path $job '.cancel'))) {
            Write-Runner 'stopped' 'Job stopped; start/retry in KADR before running this script again'; return
        }
        $automation = Read-ExchangeJson (Join-Path $root 'automation.json')
        if (-not $automation.enabled) { throw 'Enable automatic file reception in KADR first' }
        foreach ($completedId in @($workers.Keys)) {
            $worker = $workers[$completedId]
            if ($worker.State -in @('Completed','Failed','Stopped')) {
                $packetId = $completedId
                # Receive each worker once. A failed paid attempt is never relaunched.
                Receive-Job -Job $worker -ErrorAction Stop | Out-Null
                if ($worker.State -ne 'Completed') { throw 'Official CLI worker failed' }
                Remove-Job -Job $worker
                $workers.Remove($completedId)
                Write-Runner $(if ($workers.Count) { 'processing' } else { 'waiting' }) 'Results published; waiting for validation'
            }
        }
        # Drain already running siblings, then block all new account calls.
        # Only the owning Python worker re-arms a failed marker after reset.
        $cooldownPath = Join-Path $root 'quota-cooldown.json'
        if ($ManagedStopFile -and (Test-Path -LiteralPath $cooldownPath)) {
            $cooldown = Read-ExchangeJson $cooldownPath
            if ($cooldown.code -ne 'quota' -or $cooldown.packet -notmatch '^[a-f0-9]{64}$') {
                throw 'Invalid quota cooldown'
            }
            if ([DateTimeOffset]::Parse($cooldown.quota_retry_at) -gt [DateTimeOffset]::UtcNow) {
                $packetId = $cooldown.packet
                Write-Runner 'waiting_quota' 'Provider quota cooldown; automatic resume scheduled'
                Start-Sleep -Milliseconds 500
                continue
            }
        }
        $exchangePath = Join-Path $root 'exchange.json'
        if (Test-Path -LiteralPath $exchangePath) {
            $exchange = Read-ExchangeJson $exchangePath
            if ($exchange.status -eq 'error') { throw 'KADR rejected the result; inspect packet before retry' }
            if ($exchange.status -eq 'waiting') {
                $queue = @($exchange.packet)
                if ($null -ne $exchange.packets) { $queue = @($exchange.packets) }
                if ($queue.Count -gt 4 -or @($queue | Select-Object -Unique).Count -ne $queue.Count) {
                    throw 'Invalid independent packet queue'
                }
                foreach ($queuedId in $queue) {
                    if ($queuedId -isnot [string] -or $queuedId -notmatch '^[a-f0-9]{64}$') { throw 'Invalid packet identifier' }
                }
                foreach ($queuedId in $queue) {
                if ($workers.ContainsKey($queuedId)) { continue }
                if ($workers.Count -ge $MaxConcurrent) { break }
                $packetId = $queuedId
                $packet = Join-Path $root ('packets\' + $packetId)
                if (-not (Resolve-Path -LiteralPath $packet).Path.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) {
                    throw 'Packet outside exchange folder'
                }
                $failurePath = Join-Path $packet 'failure.json'
                if (Test-Path -LiteralPath $failurePath) {
                    $packetFailure = Read-ExchangeJson $failurePath
                    if ($ManagedStopFile -and $packetFailure.code -eq 'quota' -and $packetFailure.quota_retry_at) {
                        continue # Python owns reset validation and bounded retry authorization.
                    }
                    if ($packetFailure.packet -eq $packetId -and $packetFailure.code -eq 'empty_response') { continue }
                    if ($packetFailure.packet -eq $packetId -and $packetFailure.code -eq 'output_limit') {
                        # Backend splits whole units. Never relaunch the same
                        # truncated paid request while it publishes new work.
                        $request = Read-ExchangeJson (Join-Path $packet 'request.json')
                        $fields = @($request.schema.properties.PSObject.Properties.Name)
                        $complexText = @($request.images).Count -eq 0 -and
                            ((($fields -contains 'canonical_entities') -and ($fields -contains 'units')) -or
                             (($fields -contains 'pairs') -and ($fields -contains 'coverage')))
                        $responseMode = 'json_string'
                        $responseConfig = Join-Path $root 'text-response.json'
                        if (Test-Path -LiteralPath $responseConfig) { $responseMode = (Read-ExchangeJson $responseConfig).mode }
                        if (-not $complexText -or $responseMode -ne 'json_string' -or $packetFailure.response_mode -eq 'json_string') { continue }
                    }
                }
                if (-not (Test-Path -LiteralPath (Join-Path $packet 'agy-result.json')) -and
                    -not (Test-Path -LiteralPath (Join-Path $packet 'result.json'))) {
                    $remaining = 240
                    if ($MaxMinutes -gt 0) {
                        $remaining = [int][Math]::Floor($MaxMinutes * 60 - $timer.Elapsed.TotalSeconds)
                    }
                    # Do not launch an inevitably interrupted one-second query.
                    # A budget pause retains the pending packet and is not a CLI failure.
                    if ($remaining -lt 15) { break processing }
                    $ticketPath = Join-Path $packet 'quota-retry.json'
                    if ($ManagedStopFile -and (Test-Path -LiteralPath $ticketPath)) {
                        $ticket = Read-ExchangeJson $ticketPath
                        if ($ticket.count -isnot [long] -and $ticket.count -isnot [int]) { throw 'Invalid quota retry count' }
                        if ($ticket.count -lt 1 -or $ticket.count -gt 2 -or
                            [DateTimeOffset]::Parse($ticket.retry_at) -gt [DateTimeOffset]::UtcNow) { throw 'Invalid quota retry authorization' }
                        if (-not $quotaTickets.ContainsKey($packetId) -or $quotaTickets[$packetId] -lt $ticket.count) {
                            $null = $launched.Remove($packetId)
                            $quotaTickets[$packetId] = $ticket.count
                        }
                    }
                    if (-not $launched.Add($packetId)) { throw 'Attempt already finished without a result; inspect before retry' }
                    $remaining = [Math]::Min(240, $remaining)
                    $workers[$packetId] = Start-Job -ScriptBlock {
                        param($script, $directory, $exe, $requestedModel, $agent, $cancel, $stop, $limit, $quotaWait)
                        $ErrorActionPreference = 'Stop'
                        & $script -PacketDirectory $directory -AgyExe $exe -Model $requestedModel -DefaultAgent:$agent -StopFile $cancel -RunnerStopFile $stop -TimeLimitSeconds $limit -AllowQuotaWait:$quotaWait
                    } -ArgumentList (Join-Path $PSScriptRoot 'run_antigravity_packet.ps1'), $packet, $AgyExe, $Model, ([bool]$DefaultAgent), (Join-Path $job '.cancel'), $runnerStop, $remaining, ([bool]$ManagedStopFile)
                    Write-Runner 'processing' 'Running independent official CLI packets'
                }
                }
            }
        }
        Start-Sleep -Milliseconds 500
    }
    Write-Runner 'budget_exhausted' 'Standalone script reached its time budget; checkpoints retained'
} catch {
    if (Test-Path -LiteralPath (Join-Path $job '.cancel')) {
        Write-Runner 'stopped' 'Job cancelled; checkpoints retained'
        return
    }
    if ($MaxMinutes -gt 0 -and $timer.Elapsed.TotalMinutes -ge $MaxMinutes -and
        -not (Test-Path -LiteralPath (Join-Path $job '.cancel'))) {
        Write-Runner 'budget_exhausted' 'Standalone script reached its time budget; checkpoints retained'
        return
    }
    Write-Runner 'error' $_.Exception.Message
    throw
} finally {
    if ($workers.Count) {
        # Let the owned packet wrappers stop their native agy processes first.
        # Stop-Job alone could orphan a native child process.
        [IO.File]::WriteAllText($runnerStop, 'stop')
        $null = Wait-Job -Job @($workers.Values) -Timeout 7
        foreach ($worker in @($workers.Values)) {
            if ($worker.State -notin @('Completed','Failed','Stopped')) { Stop-Job -Job $worker }
            Remove-Job -Job $worker -Force
        }
        Remove-Item -LiteralPath $runnerStop -Force
    }
    $lock.Dispose()
}
