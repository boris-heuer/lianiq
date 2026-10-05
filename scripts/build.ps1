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
        --collect-all piper `
        run_app.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed ($LASTEXITCODE)." }
    Copy-Item -LiteralPath (Join-Path $ProjectRoot 'models') `
        -Destination (Join-Path $ProjectRoot 'dist\OfflineInterpreter\models') -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $ProjectRoot 'config') `
        -Destination (Join-Path $ProjectRoot 'dist\OfflineInterpreter\config') -Recurse -Force
    Write-Host 'Build is ready under dist\OfflineInterpreter.'
}
finally {
    Pop-Location
}
