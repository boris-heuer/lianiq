[CmdletBinding()]
param(
    [switch]$IncludeModels
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $Python)) {
    throw 'The virtual environment is missing. Run scripts\setup.ps1 first.'
}

$PiperRoot = (& $Python -c 'from pathlib import Path; import piper; print(Path(piper.__file__).resolve().parent)').Trim()
$PiperData = Join-Path $PiperRoot 'espeak-ng-data'
if (-not (Test-Path -LiteralPath $PiperData)) {
    throw "Piper eSpeak data is missing: $PiperData"
}

Push-Location $ProjectRoot
try {
    $DistRoot = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot 'dist')).TrimEnd('\') + '\'
    $ApplicationOutput = [System.IO.Path]::GetFullPath(
        (Join-Path $ProjectRoot 'dist\OfflineInterpreter')
    )
    if (-not $ApplicationOutput.StartsWith($DistRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe application output path: $ApplicationOutput"
    }
    if (Test-Path -LiteralPath $ApplicationOutput) {
        Remove-Item -LiteralPath $ApplicationOutput -Recurse -Force
    }
    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --onedir `
        --windowed `
        --name OfflineInterpreter `
        --add-data "$PiperData;piper/espeak-ng-data" `
        --collect-all ctranslate2 `
        --collect-all tokenizers `
        run_app.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed ($LASTEXITCODE)." }
    if ($IncludeModels) {
        $ModelSource = Join-Path $ProjectRoot 'models'
        if (-not (Test-Path -LiteralPath $ModelSource -PathType Container)) {
            throw 'IncludeModels requires a local models directory.'
        }
        $ManifestPath = Join-Path $ModelSource 'model-manifest.json'
        if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
            throw 'IncludeModels requires models\model-manifest.json from scripts\download_models.py.'
        }
        $Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
        $ModelDestination = Join-Path $ProjectRoot 'dist\OfflineInterpreter\models'
        New-Item -ItemType Directory -Path $ModelDestination -Force | Out-Null
        $ModelSourceRoot = [System.IO.Path]::GetFullPath($ModelSource).TrimEnd('\') + '\'
        $PackageRoot = [System.IO.Path]::GetFullPath(
            (Join-Path $ProjectRoot 'dist\OfflineInterpreter')
        ).TrimEnd('\') + '\'
        foreach ($Artifact in $Manifest.artifacts) {
            $RelativePath = [string]$Artifact.path
            if (-not $RelativePath.StartsWith('models/')) {
                throw "Unsafe model-manifest path: $RelativePath"
            }
            $SourcePath = [System.IO.Path]::GetFullPath(
                (Join-Path $ProjectRoot ($RelativePath -replace '/', '\'))
            )
            if (-not $SourcePath.StartsWith($ModelSourceRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "Unsafe model-manifest path: $RelativePath"
            }
            if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
                throw "Manifest artifact is missing: $RelativePath"
            }
            $DestinationPath = [System.IO.Path]::GetFullPath(
                (Join-Path $PackageRoot ($RelativePath -replace '/', '\'))
            )
            if (-not $DestinationPath.StartsWith($PackageRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "Unsafe package destination: $RelativePath"
            }
            New-Item -ItemType Directory -Path (Split-Path -Parent $DestinationPath) -Force | Out-Null
            Copy-Item -LiteralPath $SourcePath -Destination $DestinationPath -Force
        }
        Copy-Item -LiteralPath $ManifestPath -Destination `
            (Join-Path $ModelDestination 'model-manifest.json') -Force
        Write-Warning 'Only manifest-listed models were included. Verify their licenses before redistribution.'
    }
    $PackagedConfig = Join-Path $ProjectRoot 'dist\OfflineInterpreter\config'
    New-Item -ItemType Directory -Path $PackagedConfig -Force | Out-Null
    foreach ($ConfigName in @('settings.json', 'glossary.json')) {
        Copy-Item -LiteralPath (Join-Path $ProjectRoot "config\$ConfigName") `
            -Destination (Join-Path $PackagedConfig $ConfigName) -Force
    }
    $PackagedPiperData = Join-Path $ProjectRoot 'dist\OfflineInterpreter\_internal\piper\espeak-ng-data'
    if (-not (Test-Path -LiteralPath $PackagedPiperData)) {
        throw 'Packaged Piper eSpeak data is missing.'
    }
    Write-Host 'Build is ready under dist\OfflineInterpreter.'
    if (-not $IncludeModels) {
        Write-Host 'This is a thin build without model weights. Provision reviewed models separately.'
    }
}
finally {
    Pop-Location
}
