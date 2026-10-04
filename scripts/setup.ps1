$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:TEMP = Join-Path $projectRoot 'temp'
$env:TMP = $env:TEMP
$env:PYTHONUTF8 = '1'
$env:PYTHONPYCACHEPREFIX = Join-Path $projectRoot 'cache\pycache'
$env:PIP_CACHE_DIR = Join-Path $projectRoot 'cache\pip'
New-Item -ItemType Directory -Force -Path $env:TEMP,(Join-Path $projectRoot 'cache\downloads'),(Join-Path $projectRoot 'tools') | Out-Null
$projectPython = Join-Path $projectRoot 'tools\python\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    $archive = Join-Path $projectRoot 'cache\downloads\python.tar.gz'
    $partial = "$archive.partial"
    Invoke-WebRequest -Uri 'https://github.com/astral-sh/python-build-standalone/releases/download/20260929/cpython-3.12.14%2B20260929-x86_64-pc-windows-msvc-install_only_stripped.tar.gz' -OutFile $partial
    if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'f38e68f4d612ade6dd50c894fc80b14c0be0c3b5201145d6fff5f20b9323204d') {
        throw 'Portable Python checksum mismatch'
    }
    Move-Item -LiteralPath $partial -Destination $archive -Force
    & tar.exe -xzf $archive -C (Join-Path $projectRoot 'tools')
    if ($LASTEXITCODE -ne 0) { throw 'Portable Python extraction failed' }
}
& $projectPython scripts/setup.py all
if ($LASTEXITCODE -ne 0) { throw 'Setup failed' }
