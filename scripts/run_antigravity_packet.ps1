param(
    [Parameter(Mandatory=$true)][string]$PacketDirectory,
    [string]$AgyExe,
    [string]$Model = 'gemini-3.8-flash-low',
    [switch]$DefaultAgent,
    [switch]$Smoke,
    [string]$StopFile,
    [string]$RunnerStopFile,
    [ValidateRange(1,240)][int]$TimeLimitSeconds = 240
)

# Standalone direct scripting: invoked by the user, never by KADR.
$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$packet = (Resolve-Path -LiteralPath $PacketDirectory).Path
if (-not $packet.StartsWith($workspace + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Packet must be inside the KADR workspace'
}
if (-not $AgyExe) {
    $command = Get-Command agy -ErrorAction SilentlyContinue
    if ($command) { $AgyExe = $command.Source }
    else { $AgyExe = Join-Path $env:LOCALAPPDATA 'agy\bin\agy.exe' }
}
if (-not (Test-Path -LiteralPath $AgyExe -PathType Leaf)) { throw 'Official agy CLI not found' }
$env:TEMP = Join-Path $workspace 'temp'
$env:TMP = $env:TEMP
$env:TMPDIR = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
Set-Location -LiteralPath $packet
$attempt = Join-Path $packet ('cli-attempts\' + (Get-Date).ToUniversalTime().ToString('yyyyMMdd_HHmmss') + '_' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $attempt | Out-Null
if ($Smoke) {
    $schemaPath = Join-Path $packet 'smoke-schema.json'
    [IO.File]::WriteAllText($schemaPath,
        '{"type":"object","properties":{"ok":{"type":"boolean"}},"required":["ok"],"additionalProperties":false}',
        (New-Object Text.UTF8Encoding($false)))
    $promptText = 'Return the JSON object {"ok":true}. Do not use tools, shell, internet or change files.'
    $outputName = 'smoke-result.json'
} else {
    if (-not (Test-Path -LiteralPath (Join-Path $packet 'request.json'))) { throw 'request.json missing' }
    $schemaPath = Join-Path $packet 'schema.json'
    $request = Get-Content -LiteralPath (Join-Path $packet 'request.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $mentions = @()
    foreach ($page in $request.images) {
        if ($page -notmatch '^page_[0-9]{3}\.jpg$' -or -not (Test-Path -LiteralPath (Join-Path $packet $page))) {
            throw 'Invalid packet image'
        }
        $mentions += '@' + $page
    }
    # Inline the exact text contract: headless mode need not request a file-read
    # permission just to obtain the prompt. Images use official @ attachments.
    $promptText = [IO.File]::ReadAllText((Join-Path $packet 'prompt.txt'), [Text.Encoding]::UTF8) + "`n`n" + ($mentions -join ' ') + ' Return the requested JSON. Do not run shell commands, use internet, modify files or inspect other directories.'
    # Gemini's generation schema omits unsupported numeric/boolean enums.
    # Explicitly supply the ORIGINAL values; native import remains strict.
    if (-not (Test-Path -LiteralPath (Join-Path $packet 'batch.json'))) {
        $promptText += "`nOriginal contract, including every numeric/boolean enum. Use only these allowed values:`n" + ($request.schema | ConvertTo-Json -Depth 100 -Compress)
    }
    $promptText += "`nBefore returning any keep_units/preserve_silent_units/omit_units answer: their selected union and omitted unit IDs must be DISJOINT and together cover ALL allowed unit IDs. A preserved silent unit is retained and must never also appear in omit_units. Check this separately for every independent task; do not transfer unit IDs between tasks."
    $outputName = 'agy-result.json'
}
$cliArguments = @('--print', $promptText, '--output-format', 'json', '--json-schema', $schemaPath,
                  '--print-timeout', '3m', '--disable-slash-commands', '--add-dir', $packet,
                  '--log-file', (Join-Path $attempt 'agy.log'))
if ($Model) { $cliArguments += @('--model', $Model) }
$agentRequested = 'default'
if (-not $DefaultAgent) {
    $persona = Join-Path $workspace '.agents\agents\kadr-json\agent.md'
    if (-not (Test-Path -LiteralPath $persona -PathType Leaf)) { throw 'KADR JSON persona missing; restore agent.md or explicitly use -DefaultAgent' }
    $agentRequested = 'kadr-json'
    $cliArguments += @('--agent', $agentRequested)
}
$streamInput = $false
$inputMessage = $null
$started = [Diagnostics.Stopwatch]::StartNew()
# No permission bypass, token extraction, proxies, account switching or retries.
function ConvertTo-NativeArgument([string]$Value) {
    # Windows CommandLineToArgvW convention: double backslashes preceding a
    # quote, escape the quote, and double trailing backslashes before closing.
    '"' + [regex]::Replace([regex]::Replace($Value, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1') + '"'
}
$startInfo = New-Object Diagnostics.ProcessStartInfo
$startInfo.FileName = $AgyExe
$startInfo.Arguments = ($cliArguments | ForEach-Object { ConvertTo-NativeArgument $_ }) -join ' '
if ($startInfo.FileName.Length + $startInfo.Arguments.Length + 3 -ge 32767) {
    if (-not $Smoke -and @($request.images).Count -gt 0) {
        throw 'Image packet exceeds Windows command-line limit; split without truncating input. Stream image parity is not verified.'
    }
    # Official1.3.3 stream-json takes NDJSON user messages from stdin, with
    # NO --print argument. Preserve the complete prompt and attachment text.
    # Do not mistake ordinary text stdin (unsupported) for this protocol.
    $streamInput = $true
    $streamArguments = @('--input-format','stream-json','--output-format','stream-json') + $cliArguments[4..($cliArguments.Length-1)]
    $startInfo.Arguments = ($streamArguments | ForEach-Object { ConvertTo-NativeArgument $_ }) -join ' '
    $inputMessage = @{event='user';message=@{role='user';content=@(@{type='text';text=$promptText})}} | ConvertTo-Json -Depth 10 -Compress
    if ([Text.Encoding]::UTF8.GetByteCount($inputMessage) -gt 1048576) { throw 'Input exceeds standalone1MiB guard; split without truncation' }
    $startInfo.RedirectStandardInput = $true
}
$startInfo.WorkingDirectory = $packet
$startInfo.UseShellExecute = $false
$startInfo.CreateNoWindow = $true
$startInfo.RedirectStandardOutput = $true
$startInfo.RedirectStandardError = $true
$startInfo.StandardOutputEncoding = New-Object Text.UTF8Encoding($false)
$startInfo.StandardErrorEncoding = New-Object Text.UTF8Encoding($false)
$process = New-Object Diagnostics.Process
$process.StartInfo = $startInfo
$abortReason = $null
$cliStartedAt = $null
$cliFinishedAt = $null
try {
    if (($StopFile -and (Test-Path -LiteralPath $StopFile)) -or
        ($RunnerStopFile -and (Test-Path -LiteralPath $RunnerStopFile))) { throw 'Job cancelled before CLI launch' }
    if ($startInfo.FileName.Length + $startInfo.Arguments.Length + 3 -ge 32767) {
        throw 'Packet exceeds Windows command-line limit before CLI launch; split without truncating input'
    }
    # Bypass PowerShell 5 native marshalling, which strips embedded quotes.
    $cliStartedAt = (Get-Date).ToUniversalTime().ToString('o')
    $null = $process.Start()
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    # Async stdin avoids deadlocking while a model/process emits stdout.
    $stdinTask = $null
    if ($streamInput) {
        # Windows PowerShell5/.NET Framework lacks StandardInputEncoding.
        # Explicit UTF-8 without BOM preserves non-ASCII source dialogue.
        $stdinWriter = [IO.StreamWriter]::new($process.StandardInput.BaseStream, [Text.UTF8Encoding]::new($false))
        $stdinTask = $stdinWriter.WriteLineAsync($inputMessage)
    }
    $stdinClosed = -not $streamInput
    while (-not $process.WaitForExit(500)) {
        if (-not $stdinClosed -and $stdinTask.IsCompleted) {
            $stdinTask.GetAwaiter().GetResult()
            $stdinWriter.Close()
            $stdinClosed = $true
        }
        if (($StopFile -and (Test-Path -LiteralPath $StopFile)) -or
            ($RunnerStopFile -and (Test-Path -LiteralPath $RunnerStopFile)) -or $started.Elapsed.TotalSeconds -ge $TimeLimitSeconds) {
            $process.Kill()
            $process.WaitForExit()
            $abortReason = "agy cancelled or exceeded outer limit of $TimeLimitSeconds seconds"
            break
        }
    }
    $captured = $stdoutTask.GetAwaiter().GetResult()
    [IO.File]::WriteAllText((Join-Path $attempt 'agy.stderr.txt'), $stderrTask.GetAwaiter().GetResult(), (New-Object Text.UTF8Encoding($false)))
    $cliExit = $process.ExitCode
    $cliFinishedAt = (Get-Date).ToUniversalTime().ToString('o')
} finally {
    $process.Dispose()
}
$streamError = $null
if ($streamInput) {
    [IO.File]::WriteAllText((Join-Path $attempt 'agy.stream.jsonl'), $captured, (New-Object Text.UTF8Encoding($false)))
    $finalResults = @()
    try {
        foreach ($line in ($captured -split "`r?`n")) {
            if (-not $line.Trim()) { continue }
            $record = $line | ConvertFrom-Json
        if ($record.event -eq 'result') { $finalResults += $line }
        }
        if ($finalResults.Count -ne 1) { throw 'Expected one final official stream result' }
        # Retain the original final JSON line. Native strict import must still
        # see duplicate keys/NaN; PowerShell must not normalize them away.
        $captured = $finalResults[0]
    } catch {
        $streamError = 'Official stream did not contain one valid final result'
        $captured = '{}'
    }
}
$captured | Set-Content -LiteralPath (Join-Path $attempt $outputName) -Encoding UTF8
# Numeric telemetry covers the attempt even if its structured answer is rejected.
# Thinking is already part of output_tokens; never add it to total_tokens.
$reportedUsage = @{}
try {
    $envelope = $captured | ConvertFrom-Json
    if ($streamInput) { $envelope = $envelope.result }
    foreach ($field in @('input_tokens','output_tokens','thinking_tokens','cache_read_tokens','total_tokens')) {
        $counter = $envelope.usage.$field
        if (($counter -is [int] -or $counter -is [long]) -and $counter -ge 0 -and $counter -le 1000000000000) {
            $reportedUsage[$field] = $counter
        }
    }
} catch { } # Missing/malformed usage remains unknown; strict import is unchanged.
$usageReported = $reportedUsage.ContainsKey('total_tokens') -or (
    $reportedUsage.ContainsKey('input_tokens') -and $reportedUsage.ContainsKey('output_tokens'))
@{exit_code=$cliExit;wall_seconds=$started.Elapsed.TotalSeconds;started_at=$cliStartedAt;finished_at=$cliFinishedAt;official_cli=$true;model_requested=$Model;agent_requested=$agentRequested;abort_reason=$abortReason;command_line_chars=$startInfo.FileName.Length+$startInfo.Arguments.Length+3;
    input_format=$(if ($streamInput) { 'stream-json' } else { 'text' });stream_error=$streamError;usage_reported=$usageReported;usage=$reportedUsage} |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $attempt 'cli-run.json') -Encoding UTF8
if ($abortReason) { throw "$abortReason; inspect $attempt" }
if ($cliExit -ne 0) { throw "agy failed (exit $cliExit); inspect $attempt" }
if ($streamError) { throw "$streamError; inspect $attempt" }
$result = Get-Content -LiteralPath (Join-Path $attempt $outputName) -Raw -Encoding UTF8 | ConvertFrom-Json
if ($streamInput) { $result = $result.result }
if ($result.status -ne 'SUCCESS' -or $null -eq $result.structured_output) {
    throw "No successful structured result; do not import $attempt"
}
if ($Smoke -and $result.structured_output.ok -ne $true) { throw 'Smoke answer is not ok=true' }
$destination = Join-Path $packet $outputName
$pending = $destination + '.pending'
Copy-Item -LiteralPath (Join-Path $attempt $outputName) -Destination $pending -Force
if (Test-Path -LiteralPath $destination) { [IO.File]::Replace($pending, $destination, [NullString]::Value) }
else { [IO.File]::Move($pending, $destination) }
Write-Host ('Result: ' + (Join-Path $packet $outputName))
Write-Host ('CLI wall seconds: ' + [Math]::Round($started.Elapsed.TotalSeconds, 3))
if ($result.usage) { $result.usage | ConvertTo-Json -Compress | Write-Host }
