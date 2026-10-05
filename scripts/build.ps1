[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $Python)) {
    throw 'The virtual environment is missing. Run scripts\setup.ps1 first.'
}

Push-Location $ProjectRoot
try {
    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --onedir `
        --windowed `
        --name OfflineInterpreter `
        --collect-all ctranslate2 `
        --collect-all tokenizers `
        run_app.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed ($LASTEXITCODE)." }
    $ModelSource = Join-Path $ProjectRoot 'models'
    $ModelDestination = Join-Path $ProjectRoot 'dist\OfflineInterpreter\models'
    New-Item -ItemType Directory -Path $ModelDestination -Force | Out-Null
    & robocopy $ModelSource $ModelDestination /E /XD '.cache' /XF 'tf_model.h5' | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Model copy failed ($LASTEXITCODE)." }
    Copy-Item -LiteralPath (Join-Path $ProjectRoot 'config') `
        -Destination (Join-Path $ProjectRoot 'dist\OfflineInterpreter\config') -Recurse -Force
    Write-Host 'Build is ready under dist\OfflineInterpreter.'
}
finally {
    Pop-Location
}
