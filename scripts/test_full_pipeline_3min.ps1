param(
    [ValidateSet('offline', 'real')][string]$Mode = 'offline',
    [string]$Source,
    [string]$Transcript,
    [string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $root

# No global installation, no writes outside the project.
$portablePython = Join-Path $root 'tools\python\python.exe'
$venvPython = Join-Path $root '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $venvPython) { $python = $venvPython }
elseif (Test-Path -LiteralPath $portablePython) { $python = $portablePython }
else {
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $command) { throw 'Не найден Python. Установите локальное окружение проекта через setup.bat.' }
    $python = $command.Source
}
$ffmpeg = Join-Path $root 'tools\ffmpeg\bin\ffmpeg.exe'
$ffprobe = Join-Path $root 'tools\ffmpeg\bin\ffprobe.exe'
if (-not (Test-Path -LiteralPath $ffmpeg) -or -not (Test-Path -LiteralPath $ffprobe)) {
    throw 'Нужны локальные tools\ffmpeg\bin\ffmpeg.exe и ffprobe.exe. Запустите setup.bat.'
}
$env:PYTHONUTF8 = '1'
$env:TEMP = Join-Path $root 'temp'
$env:TMP = $env:TEMP
$env:PYTHONPYCACHEPREFIX = Join-Path $root 'cache\test-pycache'
New-Item -ItemType Directory -Force -Path $env:TEMP, (Join-Path $root 'cache') | Out-Null

$arguments = @('scripts/full_pipeline_3min.py', '--mode', $Mode)
if ($Source) { $arguments += @('--source', $Source) }
if ($Transcript) { $arguments += @('--transcript', $Transcript) }
if ($OutputDirectory) { $arguments += @('--directory', $OutputDirectory) }
if ($Mode -eq 'real' -and -not $Source) {
    throw 'Для настоящего смыслового теста укажите -Source с трёхминутным сюжетным MP4 внутри папки проекта.'
}
Write-Host "KADR 3-minute E2E: mode=$Mode; python=$python"
Write-Host 'Результаты сохраняются в temp\full-pipeline-3min.'
& $python @arguments
$exitCode = $LASTEXITCODE
Write-Host "Завершение теста: код $exitCode"
exit $exitCode
