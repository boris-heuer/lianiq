[CmdletBinding()]
param(
    [switch]$SkipModels
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $VenvPython)) {
    py -3.12 -m venv (Join-Path $ProjectRoot '.venv')
}

& $VenvPython -m pip install --require-hashes -r (Join-Path $ProjectRoot 'requirements-lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Locked dependency installation failed.' }
& $VenvPython -m pip install --no-build-isolation --no-deps -e $ProjectRoot
if ($LASTEXITCODE -ne 0) { throw 'Editable project installation failed.' }

if (-not $SkipModels) {
    & $VenvPython (Join-Path $PSScriptRoot 'download_models.py')
}

& $VenvPython (Join-Path $PSScriptRoot 'doctor.py')
Write-Host "Launch: $VenvPython -m offline_translator"
