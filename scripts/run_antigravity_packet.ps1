param(
    [Parameter(Mandatory=$true)][string]$PacketDirectory,
    [string]$AgyExe,
    [string]$Model = 'gemini-3.8-flash-low',
    [switch]$Smoke,
    [string]$StopFile,
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
    $outputName = 'agy-result.json'
}
$cliArguments = @('--print', $promptText, '--output-format', 'json', '--json-schema', $schemaPath,
                  '--print-timeout', '3m', '--disable-slash-commands', '--add-dir', $packet,
                  '--log-file', (Join-Path $attempt 'agy.log'))
if ($Model) { $cliArguments += @('--model', $Model) }
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
try {
    if ($StopFile -and (Test-Path -LiteralPath $StopFile)) { throw 'Job cancelled before CLI launch' }
    # Bypass PowerShell 5 native marshalling, which strips embedded quotes.
    $null = $process.Start()
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    while (-not $process.WaitForExit(500)) {
        if (($StopFile -and (Test-Path -LiteralPath $StopFile)) -or $started.Elapsed.TotalSeconds -ge $TimeLimitSeconds) {
            $process.Kill()
            $process.WaitForExit()
            $abortReason = "agy cancelled or exceeded outer limit of $TimeLimitSeconds seconds"
            break
        }
    }
    $captured = $stdoutTask.GetAwaiter().GetResult()
    [IO.File]::WriteAllText((Join-Path $attempt 'agy.stderr.txt'), $stderrTask.GetAwaiter().GetResult(), (New-Object Text.UTF8Encoding($false)))
    $cliExit = $process.ExitCode
} finally {
    $process.Dispose()
}
$captured | Set-Content -LiteralPath (Join-Path $attempt $outputName) -Encoding UTF8
@{exit_code=$cliExit;wall_seconds=$started.Elapsed.TotalSeconds;official_cli=$true;model_requested=$Model;abort_reason=$abortReason} |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $attempt 'cli-run.json') -Encoding UTF8
if ($abortReason) { throw "$abortReason; inspect $attempt" }
if ($cliExit -ne 0) { throw "agy failed (exit $cliExit); inspect $attempt" }
$result = Get-Content -LiteralPath (Join-Path $attempt $outputName) -Raw -Encoding UTF8 | ConvertFrom-Json
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
