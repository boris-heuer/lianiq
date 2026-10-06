[CmdletBinding()]
param(
    [ValidateSet('Thin', 'Operational')]
    [string]$Mode = 'Thin',
    [string]$SourcePath = (Split-Path -Parent $PSScriptRoot),
    [string]$RepositoryUrl,
    [string]$Ref,
    [string]$PythonExecutable = 'py',
    [string]$PythonVersion = '-3.12',
    [string]$ModelSourcePath,
    [switch]$KeepWorktree
)

<#
.SYNOPSIS
Verifies that the committed project can be installed from a fresh local clone.

.DESCRIPTION
RepositoryUrl selects a remote repository; optionally provide Ref as a remote
branch or tag. Without RepositoryUrl, SourcePath is cloned locally with
--no-local, so Git cannot share objects with the source worktree.

Thin mode creates an isolated clone and virtual environment, installs the package
and development tools without a pip cache, then runs pip check, Ruff, pytest,
a wheel build, an import of that built wheel, and a thin PyInstaller application
build. It deliberately neither downloads nor reuses speech, translation, or voice models.

Operational mode additionally runs scripts/doctor.py against the clone. Models
are supplied explicitly with ModelSourcePath and copied into the clone; this
script never downloads models or reads a Hugging Face cache. Use it to validate
a release candidate with intended local runtime assets, not as a substitute for
the Thin packaging check.
#>

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$workRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("translator-clean-clone-" + [guid]::NewGuid())
$clonePath = Join-Path $workRoot 'repository'
$venvPath = Join-Path $clonePath '.venv'
$cachePath = Join-Path $workRoot 'empty-cache'

New-Item -ItemType Directory -Path $cachePath -Force | Out-Null

try {
    if ([string]::IsNullOrWhiteSpace($RepositoryUrl)) {
        $source = (Resolve-Path -LiteralPath $SourcePath).Path
        if (-not (Test-Path -LiteralPath (Join-Path $source '.git'))) {
            throw "SourcePath must be a Git working tree: $source"
        }
        # --no-local prevents Git from sharing objects with the source repository.
        & git clone --no-local --depth 1 -- $source $clonePath
    }
    elseif ([string]::IsNullOrWhiteSpace($Ref)) {
        & git clone --depth 1 -- $RepositoryUrl $clonePath
    }
    else {
        & git clone --depth 1 --branch $Ref -- $RepositoryUrl $clonePath
    }
    if ($LASTEXITCODE -ne 0) { throw 'git clone failed.' }

    if ($Mode -eq 'Operational') {
        if ([string]::IsNullOrWhiteSpace($ModelSourcePath)) {
            throw 'Operational mode requires -ModelSourcePath with explicitly provisioned model artifacts.'
        }
        $modelSource = (Resolve-Path -LiteralPath $ModelSourcePath).Path
        if (-not (Test-Path -LiteralPath $modelSource -PathType Container)) {
            throw "ModelSourcePath must be a directory: $modelSource"
        }
        Copy-Item -LiteralPath $modelSource -Destination (Join-Path $clonePath 'models') -Recurse
    }

    $previousPipNoCache = $env:PIP_NO_CACHE_DIR
    $previousPipCache = $env:PIP_CACHE_DIR
    $previousHfHome = $env:HF_HOME
    $env:PIP_NO_CACHE_DIR = '1'
    $env:PIP_CACHE_DIR = $cachePath
    $env:HF_HOME = (Join-Path $cachePath 'huggingface')

    try {
        & $PythonExecutable $PythonVersion -m venv $venvPath
        if ($LASTEXITCODE -ne 0) { throw "Could not create a virtual environment with '$PythonExecutable $PythonVersion'." }

        $python = Join-Path $venvPath 'Scripts\python.exe'
        & $python -m pip install --no-cache-dir --require-hashes -r `
            (Join-Path $clonePath 'requirements-lock.txt')
        if ($LASTEXITCODE -ne 0) { throw 'Locked dependency installation failed.' }
        & $python -m pip install --no-build-isolation --no-deps -e $clonePath
        if ($LASTEXITCODE -ne 0) { throw 'Editable package installation failed.' }
        & $python -m pip check
        if ($LASTEXITCODE -ne 0) { throw 'pip dependency verification failed.' }
        & $python -m ruff check $clonePath
        if ($LASTEXITCODE -ne 0) { throw 'Ruff validation failed.' }
        & $python -m pytest $clonePath
        if ($LASTEXITCODE -ne 0) { throw 'Pytest validation failed.' }
        $wheelDirectory = Join-Path $workRoot 'wheel'
        & $python -m pip wheel --no-build-isolation --no-deps --wheel-dir $wheelDirectory $clonePath
        if ($LASTEXITCODE -ne 0) { throw 'Wheel build failed.' }
        $wheel = Get-ChildItem -LiteralPath $wheelDirectory -Filter '*.whl' | Select-Object -First 1
        if ($null -eq $wheel) { throw 'Wheel build did not produce an artifact.' }
        $smokeVenv = Join-Path $workRoot 'package-smoke'
        & $python -m venv $smokeVenv
        if ($LASTEXITCODE -ne 0) { throw 'Package smoke-test virtual environment creation failed.' }
        $smokePython = Join-Path $smokeVenv 'Scripts\python.exe'
        & $smokePython -m pip install --no-deps $wheel.FullName
        if ($LASTEXITCODE -ne 0) { throw 'Built-wheel installation failed.' }
        & $smokePython -c 'import offline_translator; print(f"Built package version: {offline_translator.__version__}")'
        if ($LASTEXITCODE -ne 0) { throw 'Built-package import smoke test failed.' }

        & (Join-Path $clonePath 'scripts\build.ps1')
        if ($LASTEXITCODE -ne 0) { throw 'Thin Windows application build failed.' }
        $application = Join-Path $clonePath 'dist\OfflineInterpreter\OfflineInterpreter.exe'
        if (-not (Test-Path -LiteralPath $application -PathType Leaf)) {
            throw 'Thin Windows application build did not produce OfflineInterpreter.exe.'
        }
        if (Test-Path -LiteralPath (Join-Path $clonePath 'dist\OfflineInterpreter\models')) {
            throw 'Thin Windows application build unexpectedly contains model artifacts.'
        }
        if (Test-Path -LiteralPath `
            (Join-Path $clonePath 'dist\OfflineInterpreter\config\settings.local.json')) {
            throw 'Thin Windows application build unexpectedly contains private local settings.'
        }
        $applicationProcess = Start-Process -FilePath $application -PassThru -WindowStyle Hidden
        try {
            Start-Sleep -Seconds 5
            if ($applicationProcess.HasExited) {
                throw "Packaged application exited early with code $($applicationProcess.ExitCode)."
            }
        }
        finally {
            if (-not $applicationProcess.HasExited) {
                Stop-Process -Id $applicationProcess.Id -Force
            }
        }

        if ($Mode -eq 'Operational') {
            & $python (Join-Path $clonePath 'scripts\doctor.py') --require-mandarin-voice
            if ($LASTEXITCODE -ne 0) {
                throw 'Operational verification failed. Provision all documented local models in the clone; no model download was attempted.'
            }
        }
    }
    finally {
        $env:PIP_NO_CACHE_DIR = $previousPipNoCache
        $env:PIP_CACHE_DIR = $previousPipCache
        $env:HF_HOME = $previousHfHome
    }
}
finally {
    if ($KeepWorktree) {
        Write-Host "Clean clone retained at: $workRoot"
    }
    elseif (Test-Path -LiteralPath $workRoot) {
        Remove-Item -LiteralPath $workRoot -Recurse -Force
    }
}
