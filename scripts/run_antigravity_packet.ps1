param(
    [Parameter(Mandatory=$true)][string]$PacketDirectory,
    [string]$AgyExe,
    [string]$Model = 'gemini-3.8-flash-low',
    [switch]$DefaultAgent,
    [switch]$Smoke,
    [switch]$JsonText,
    [switch]$EmptyResponseRetryUsed,
    [string]$StopFile,
    [string]$RunnerStopFile,
    [ValidateRange(1,240)][int]$TimeLimitSeconds = 240
)

# Standalone direct scripting: invoked by the user, never by KADR.
$ErrorActionPreference = 'Stop'
if ($Smoke -and $JsonText) { throw 'JsonText is for real analysis packets, not the structured smoke check' }
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
    # permission just to obtain the prompt. Print-mode @ mentions are text;
    # the restricted persona must open the exact images using view_file.
    $promptText = [IO.File]::ReadAllText((Join-Path $packet 'prompt.txt'), [Text.Encoding]::UTF8) + "`n`n" + ($mentions -join ' ') + ' Return the requested JSON. Do not run shell commands, use internet, modify files or inspect other directories.'
    if (@($request.images).Count -gt 0) {
        $imagePaths = @($request.images | ForEach-Object { Join-Path $packet $_ })
        $promptText += "`nREQUIRED IMAGE RECEPTION: @ mentions in print mode are text, not attached pixels. Before answering, use view_file to open EACH of these exact original image paths: " + ($imagePaths -join ', ') + '. Only these image paths may be read. If any image cannot be viewed, report uncertainty; never guess from ASR or filenames.'
    }
    # Gemini's generation schema omits unsupported numeric/boolean enums.
    # Explicitly supply the ORIGINAL values; native import remains strict.
    if (-not (Test-Path -LiteralPath (Join-Path $packet 'batch.json'))) {
        $promptText += "`nOriginal contract, including every numeric/boolean enum. Use only these allowed values:`n" + ($request.schema | ConvertTo-Json -Depth 100 -Compress)
    }
    $promptText += "`nBefore returning any keep_units/preserve_silent_units/omit_units answer: their selected union and omitted unit IDs must be DISJOINT and together cover ALL allowed unit IDs. A preserved silent unit is retained and must never also appear in omit_units. Check this separately for every independent task; do not transfer unit IDs between tasks."
    $outputName = 'agy-result.json'
}
if (-not $Smoke -and -not $JsonText -and @($request.images).Count -eq 0) {
    $fields = @($request.schema.properties.PSObject.Properties.Name)
    $complexText = (($fields -contains 'canonical_entities') -and ($fields -contains 'units')) -or
        (($fields -contains 'pairs') -and ($fields -contains 'coverage'))
    $responseConfig = Join-Path (Split-Path (Split-Path $packet -Parent) -Parent) 'text-response.json'
    $responseMode = 'json_string'
    if (Test-Path -LiteralPath $responseConfig) {
        $responseMode = (Get-Content -LiteralPath $responseConfig -Raw -Encoding UTF8 | ConvertFrom-Json).mode
        if ($responseMode -notin @('json_string','structured')) { throw 'Invalid text-response.json mode' }
    }
    if ($complexText -and $responseMode -eq 'json_string') { $JsonText = $true }
}
function Publish-Failure([string]$Code) {
    if ($Smoke) { return }
    $failure = Join-Path $packet 'failure.json'
    $failurePending = $failure + '.pending'
    $failureRecord = @{packet=$request.id;code=$Code;attempt=(Split-Path $attempt -Leaf);
        response_mode=$(if ($JsonText) { 'json_string' } else { 'structured' })}
    if ($Code -eq 'process_exit') { $failureRecord.exit_code = $cliExit }
    [IO.File]::WriteAllText($failurePending, ($failureRecord | ConvertTo-Json -Compress), [Text.UTF8Encoding]::new($false))
    if (Test-Path -LiteralPath $failure) { [IO.File]::Replace($failurePending,$failure,[NullString]::Value) }
    else { [IO.File]::Move($failurePending,$failure) }
}
if (-not $Smoke -and (Test-Path -LiteralPath (Join-Path $packet 'failure.json'))) {
    $previousFailure = Get-Content -LiteralPath (Join-Path $packet 'failure.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($previousFailure.packet -eq $request.id -and $previousFailure.code -eq 'output_limit' -and
        (-not $JsonText -or $previousFailure.response_mode -eq 'json_string')) {
        Write-Host 'Output limit already confirmed; waiting for a smaller native packet.'
        return
    }
}
if ($JsonText) {
    # A small string envelope avoids the large nested Gemini finish-tool
    # grammar. Original source/schema remain in the input; KADR validates
    # the decoded JSON with its unchanged original contract on import.
    $schemaPath = Join-Path $packet 'reply-schema.json'
    [IO.File]::WriteAllText($schemaPath, '{"type":"object","properties":{"kadr_answer_json":{"type":"string"}},"required":["kadr_answer_json"],"additionalProperties":false}', [Text.UTF8Encoding]::new($false))
    $promptText += "`nTransport envelope: return ONLY kadr_answer_json, a string containing the COMPLETE raw JSON object matching the ORIGINAL contract above. No markdown fences, toolAction/toolSummary, prose or extra envelope keys. All ORIGINAL fields, references, citations and native constraints still apply INSIDE that JSON string."
    $promptText += "`nSource contract reminders: every arc.anchor MUST also appear in that arc.members with its evidenced role and its own support. A closed arc requires a DIRECT supported relation from anchor to closing_unit, a payoff closing role and an evidenced outcome; an indirect chain alone does not close it. Keep unsupported arcs open. A canonical before/after ID needs an observed mention from THAT EXACT unit ref; a neighboring unit's entity mention does not populate its states. Use null/[] for unsupported canonical facts, without suppressing separately evidenced story roles. Every non-unknown unit row cites its own inherited proof."
    $promptText += "`nEvery returned relation MUST have at least one endpoint in CURRENT. Do not return a relation only between MEMORY and CONTEXT_ONLY, or between two CONTEXT_ONLY refs. Relations follow source time from earlier to later. Every arc has at least one CURRENT member. Return entities/relations/arcs only when their actual supported confidence meets the native 0.9 minimum; omit unsupported claims, never inflate confidence to satisfy validation."
}
$streamOutput = (-not $Smoke -and @($request.images).Count -gt 0)
$cliArguments = @('--print', $promptText, '--output-format', $(if ($streamOutput) { 'stream-json' } else { 'json' }), '--json-schema', $schemaPath)
$cliArguments += @('--print-timeout', '3m', '--disable-slash-commands', '--add-dir', $packet,
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
    $streamOutput = $true
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
            $null = $stdinTask.GetAwaiter().GetResult()
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
$viewedImages = @()
if ($streamOutput) {
    [IO.File]::WriteAllText((Join-Path $attempt 'agy.stream.jsonl'), $captured, (New-Object Text.UTF8Encoding($false)))
    $finalResults = @()
    try {
        foreach ($line in ($captured -split "`r?`n")) {
            if (-not $line.Trim()) { continue }
            $record = $line | ConvertFrom-Json
            if ($record.event -eq 'step_update' -and $record.step_update.step_type -eq 'tool' -and
                $record.step_update.state -eq 'DONE' -and $record.step_update.tool_name -eq 'view_file' -and
                -not $record.step_update.error) {
                $viewedImages += [string]$record.step_update.tool_info.parameters.AbsolutePath
            }
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
    if ($streamOutput) { $envelope = $envelope.result }
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
    input_format=$(if ($streamInput) { 'stream-json' } else { 'text' });
    response_mode=$(if ($JsonText) { 'json_string' } else { 'structured' });
    stream_error=$streamError;usage_reported=$usageReported;usage=$reportedUsage} |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $attempt 'cli-run.json') -Encoding UTF8
if ($abortReason) {
    if (-not ($StopFile -and (Test-Path -LiteralPath $StopFile)) -and
        -not ($RunnerStopFile -and (Test-Path -LiteralPath $RunnerStopFile))) { Publish-Failure 'timeout' }
    throw "$abortReason; inspect $attempt"
}
if ($cliExit -ne 0) { Publish-Failure 'process_exit'; throw "agy failed (exit $cliExit); inspect $attempt" }
if ($streamError) { Publish-Failure 'invalid_json'; throw "$streamError; inspect $attempt" }
try { $result = Get-Content -LiteralPath (Join-Path $attempt $outputName) -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { Publish-Failure 'invalid_json'; throw "Antigravity returned invalid JSON; inspect $attempt" }
if ($streamOutput) { $result = $result.result }
$hasAnswer = $null -ne $result.structured_output
if ($JsonText -and $result.status -eq 'SUCCESS') {
    $hasAnswer = ($result.structured_output.kadr_answer_json -is [string]) -and
        ([string]$result.structured_output.kadr_answer_json).Length -gt 0
}
if ($result.status -ne 'SUCCESS' -or -not $hasAnswer) {
    # Observed official CLI failure: SUCCESS, no body, duration0 and explicit
    # zero usage. Retry this narrow empty completion once; never retry ERROR,
    # quota, a partial answer, or a completion with unknown/nonzero usage.
    $emptySuccess = $result.status -eq 'SUCCESS' -and $null -eq $result.structured_output -and
        [string]::IsNullOrWhiteSpace([string]$result.response) -and $result.duration_seconds -eq 0
    foreach ($field in @('input_tokens','output_tokens','thinking_tokens','cache_read_tokens','total_tokens')) {
        if (-not $reportedUsage.ContainsKey($field) -or $reportedUsage[$field] -ne 0) { $emptySuccess = $false }
    }
    if ($emptySuccess) {
        if ($Smoke) { throw 'Smoke returned empty SUCCESS' }
        $remaining = [int][Math]::Floor($TimeLimitSeconds - $started.Elapsed.TotalSeconds)
        if (-not $Smoke -and -not $EmptyResponseRetryUsed -and $remaining -ge 15 -and
            -not ($StopFile -and (Test-Path -LiteralPath $StopFile)) -and
            -not ($RunnerStopFile -and (Test-Path -LiteralPath $RunnerStopFile))) {
            Write-Host 'Official CLI returned an empty SUCCESS with zero reported usage; retrying once.'
            & $PSCommandPath -PacketDirectory $packet -AgyExe $AgyExe -Model $Model -DefaultAgent:$DefaultAgent -JsonText:$JsonText -StopFile $StopFile -RunnerStopFile $RunnerStopFile -TimeLimitSeconds $remaining -EmptyResponseRetryUsed
            return
        }
        Publish-Failure 'empty_response'
        Write-Host 'Antigravity returned empty SUCCESS twice; waiting for a smaller native packet.'
        return
    }
    $reason = [string]$result.error
    if ($result.status -eq 'ERROR' -and $reason -match 'exceeded the output token limit') {
        Publish-Failure 'output_limit'
        Write-Host 'Antigravity output limit: partial response retained; waiting for a smaller native packet.'
        return
    }
    $failureCode = 'cli_error'
    if ($reason -match 'quota|rate.limit|RESOURCE_EXHAUSTED|429') { $failureCode = 'quota' }
    elseif ($reason -match 'not.logged.in|UNAUTHENTICATED|authentication') { $failureCode = 'authentication' }
    elseif ($reason -match 'timed.out|deadline.exceeded') { $failureCode = 'timeout' }
    elseif ($reason -match 'context.*(exceed|too.long)') { $failureCode = 'context_limit' }
    Publish-Failure $failureCode
    throw "No successful structured result; do not import $attempt"
}
if ($Smoke -and $result.structured_output.ok -ne $true) { throw 'Smoke answer is not ok=true' }
if (-not $Smoke -and @($request.images).Count -gt 0) {
    foreach ($requiredImage in $imagePaths) {
        if ($requiredImage -notin $viewedImages) {
            Publish-Failure 'image_reception'
            throw "Original image was not viewed; no result published: $requiredImage"
        }
    }
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try { $responseDigest = [BitConverter]::ToString($sha256.ComputeHash([IO.File]::ReadAllBytes((Join-Path $attempt $outputName)))).Replace('-','').ToLowerInvariant() }
    finally { $sha256.Dispose() }
    $receipt = @{packet=$request.id;version=1;transport='official-view-file';
        images=@($request.images);image_hashes=@($request.image_hashes);
        response_sha256=$responseDigest;
        attempt=(Split-Path $attempt -Leaf)}
    [IO.File]::WriteAllText((Join-Path $packet 'image-reception.json'), ($receipt | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
}
$destination = Join-Path $packet $outputName
$pending = $destination + '.pending'
Copy-Item -LiteralPath (Join-Path $attempt $outputName) -Destination $pending -Force
if (Test-Path -LiteralPath $destination) { [IO.File]::Replace($pending, $destination, [NullString]::Value) }
else { [IO.File]::Move($pending, $destination) }
Write-Host ('Result: ' + (Join-Path $packet $outputName))
Write-Host ('CLI wall seconds: ' + [Math]::Round($started.Elapsed.TotalSeconds, 3))
if ($result.usage) { $result.usage | ConvertTo-Json -Compress | Write-Host }
