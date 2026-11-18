<#
.SYNOPSIS
Builds a tagged Lianiq release locally and installs it for the current user.

.DESCRIPTION
Clones the tag into its own build folder (separate from every development checkout), runs
scripts\setup.ps1, scripts\build.ps1 -IncludeModels and scripts\doctor.py there, copies
dist\lianiq to <InstallRoot>\<Version> and points the "Lianiq" Desktop and Start-menu shortcuts
at the newest installed version. Older versions stay installed. No administrator rights are
needed. The result contains model weights: it is for local use only, never redistribute it.

Re-run with a newer -Version to update. Local settings (config\settings.local*.json) are carried
over from the version being replaced or from the newest installed version.

.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install-release.ps1 -Version v0.2.0
#>
[CmdletBinding()]
param(
    [string]$Version,
    [switch]$Force,
    [string]$RepositoryUrl = 'https://github.com/boris-heuer/lianiq.git',
    [string]$BuildRoot = (Join-Path $env:LOCALAPPDATA 'lianiq-release\build'),
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'Programs\lianiq'),
    [string]$ShortcutName = 'Lianiq',
    [string]$DesktopDir = [Environment]::GetFolderPath('Desktop'),
    [string]$StartMenuDir = [Environment]::GetFolderPath('Programs')
)

$ErrorActionPreference = 'Stop'
$VersionPattern = '^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$'
$LocalSettingsNames = @('settings.local.json', 'settings.local.v1.json')

function Assert-LianiqVersion([string]$Value) {
    if ([string]::IsNullOrEmpty($Value) -or $Value -cnotmatch $VersionPattern) {
        throw "Invalid version '$Value': expected vMAJOR.MINOR.PATCH, for example v0.2.0."
    }
}

function ConvertTo-LianiqVersion([string]$Value) {
    [version]$Value.Substring(1)
}

function Resolve-ChildPath([string]$Root, [string]$Name) {
    # A direct child of $Root, never the root itself or anything outside it.
    if ([string]::IsNullOrWhiteSpace($Root)) { throw 'Root path is empty.' }
    # Windows drops trailing dots and spaces, so '.. ' would name the root itself.
    $Invalid = [System.IO.Path]::GetInvalidFileNameChars()
    if ([string]::IsNullOrWhiteSpace($Name) -or $Name.IndexOfAny($Invalid) -ge 0 -or
        $Name -match '[ .]$' -or $Name -match '^\s') {
        throw "Unsafe path '$Name': it must be a plain folder name."
    }
    $RootFull = [System.IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    $ChildFull = [System.IO.Path]::GetFullPath((Join-Path $RootFull $Name)).TrimEnd('\')
    $Parent = [System.IO.Path]::GetDirectoryName($ChildFull).TrimEnd('\') + '\'
    if (-not $Parent.Equals($RootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe path '$Name': it must be a direct child of $RootFull"
    }
    $ChildFull
}

function Get-InstalledLianiq([string]$Root) {
    # Installed versions with a lianiq.exe, newest first.
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { return @() }
    $Found = foreach ($Dir in Get-ChildItem -LiteralPath $Root -Directory) {
        if ($Dir.Name -cnotmatch $VersionPattern) { continue }
        $Exe = Join-Path $Dir.FullName 'lianiq.exe'
        if (-not (Test-Path -LiteralPath $Exe -PathType Leaf)) { continue }
        [pscustomobject]@{
            Version = $Dir.Name
            Order = ConvertTo-LianiqVersion $Dir.Name
            Path = $Dir.FullName
            Exe = $Exe
        }
    }
    @($Found | Sort-Object -Property Order -Descending)
}

function Get-ShortcutTarget([string]$Root) {
    $Newest = @(Get-InstalledLianiq $Root) | Select-Object -First 1
    if ($null -eq $Newest) { throw "No installed Lianiq version under $Root" }
    $Newest
}

function Set-LianiqShortcut([string]$Directory, [string]$Name, $Install) {
    New-Item -ItemType Directory -Path $Directory -Force | Out-Null
    $LinkPath = Join-Path $Directory "$Name.lnk"
    $Shell = New-Object -ComObject WScript.Shell
    try {
        $Link = $Shell.CreateShortcut($LinkPath)
        $Link.TargetPath = $Install.Exe
        $Link.WorkingDirectory = $Install.Path
        $Link.IconLocation = "$($Install.Exe),0"
        $Link.Description = "Lianiq $($Install.Version)"
        $Link.Save()
    }
    finally {
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($Shell)
    }
    $LinkPath
}

function Copy-LocalSettings([string]$From, [string]$To) {
    if ([string]::IsNullOrEmpty($From)) { return }
    $Destination = Join-Path $To 'config'
    foreach ($Name in $LocalSettingsNames) {
        $Source = Join-Path $From "config\$Name"
        if (Test-Path -LiteralPath $Source -PathType Leaf) {
            New-Item -ItemType Directory -Path $Destination -Force | Out-Null
            Copy-Item -LiteralPath $Source -Destination (Join-Path $Destination $Name) -Force
            Write-Host "Carried over config\$Name from $From"
        }
    }
}

function Invoke-Checked([string]$Step, [scriptblock]$Command) {
    Write-Host "== $Step"
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Step failed (exit code $LASTEXITCODE)." }
}

function Initialize-BuildClone([string]$BuildDir, [string]$Tag, [string]$Url) {
    if (Test-Path -LiteralPath $BuildDir) {
        if (-not $Force) {
            throw "Build folder $BuildDir already exists. Re-run with -Force to rebuild it from a fresh clone."
        }
        Remove-Item -LiteralPath $BuildDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $BuildDir) -Force | Out-Null
    Invoke-Checked "Clone $Tag" {
        git -c advice.detachedHead=false clone --quiet --depth 1 --branch $Tag -- $Url $BuildDir
    }
    $Head = (git -C $BuildDir rev-parse HEAD).Trim()
    $Tagged = (git -C $BuildDir rev-parse "refs/tags/$Tag^{commit}").Trim()
    if ($LASTEXITCODE -ne 0 -or $Head -ne $Tagged) {
        throw "Clone of $Tag is not at the tag commit (HEAD $Head, tag $Tagged)."
    }
    Write-Host "Building $Tag at $Head"
}

function Get-SettingsSource([string]$Root, [string]$Target) {
    # The version being replaced keeps its own settings; a new version takes the newest one's.
    if (Test-Path -LiteralPath $Target -PathType Container) { return $Target }
    $Previous = @(Get-InstalledLianiq $Root) | Select-Object -First 1
    if ($null -ne $Previous) { return $Previous.Path }
    $null
}

function Publish-LianiqInstall([string]$Root, [string]$Name, [string]$Source) {
    # Copy $Source to <Root>\<Name> through a staging folder. An existing version is renamed
    # aside, never deleted in place, so a locked (running) install stays complete.
    $Target = Resolve-ChildPath $Root $Name
    $Staging = Resolve-ChildPath $Root ".staging-$Name"
    $Aside = Resolve-ChildPath $Root ".old-$Name"
    if (Test-Path -LiteralPath $Aside) {
        if (Test-Path -LiteralPath $Target) {
            Remove-Item -LiteralPath $Aside -Recurse -Force
        }
        else {
            Rename-Item -LiteralPath $Aside -NewName $Name  # an earlier run stopped mid-swap
        }
    }
    $SettingsSource = Get-SettingsSource $Root $Target
    if (Test-Path -LiteralPath $Staging) { Remove-Item -LiteralPath $Staging -Recurse -Force }
    Write-Host "== Copy to $Target"
    New-Item -ItemType Directory -Path $Root -Force | Out-Null
    Copy-Item -LiteralPath $Source -Destination $Staging -Recurse
    Copy-LocalSettings $SettingsSource $Staging
    if (Test-Path -LiteralPath $Target) {
        try {
            Rename-Item -LiteralPath $Target -NewName ".old-$Name"
        }
        catch {
            throw "Cannot replace $Target (is Lianiq still running? close it and retry): $_"
        }
    }
    try {
        Rename-Item -LiteralPath $Staging -NewName $Name
    }
    catch {
        if (Test-Path -LiteralPath $Aside) { Rename-Item -LiteralPath $Aside -NewName $Name }
        throw
    }
    if (Test-Path -LiteralPath $Aside) {
        try {
            Remove-Item -LiteralPath $Aside -Recurse -Force
        }
        catch {
            Write-Warning "Could not remove the replaced copy $Aside; the next run removes it."
        }
    }
    $Target
}

function Install-LianiqRelease {
    Assert-LianiqVersion $Version
    $Target = Resolve-ChildPath $InstallRoot $Version
    $BuildDir = Resolve-ChildPath $BuildRoot $Version
    $Aside = Resolve-ChildPath $InstallRoot ".old-$Version"  # left by an interrupted swap
    if (((Test-Path -LiteralPath $Target) -or (Test-Path -LiteralPath $Aside)) -and -not $Force) {
        throw "Lianiq $Version is already installed at $Target. Re-run with -Force to replace it."
    }

    Initialize-BuildClone $BuildDir $Version $RepositoryUrl
    $PowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    Invoke-Checked 'setup.ps1' {
        & $PowerShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $BuildDir 'scripts\setup.ps1')
    }
    Invoke-Checked 'build.ps1 -IncludeModels' {
        & $PowerShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $BuildDir 'scripts\build.ps1') -IncludeModels
    }
    Invoke-Checked 'doctor.py' {
        & (Join-Path $BuildDir '.venv\Scripts\python.exe') (Join-Path $BuildDir 'scripts\doctor.py')
    }
    $Dist = Join-Path $BuildDir 'dist\lianiq'
    foreach ($Required in @('lianiq.exe', 'models\model-manifest.json')) {
        if (-not (Test-Path -LiteralPath (Join-Path $Dist $Required) -PathType Leaf)) {
            throw "Build output is missing $Required under $Dist"
        }
    }

    Publish-LianiqInstall $InstallRoot $Version $Dist | Out-Null

    $Newest = Get-ShortcutTarget $InstallRoot
    foreach ($Directory in @($DesktopDir, $StartMenuDir)) {
        $Link = Set-LianiqShortcut $Directory $ShortcutName $Newest
        Write-Host "Shortcut $Link -> $($Newest.Exe)"
    }
    if ($Newest.Version -ne $Version) {
        Write-Warning "$Version is installed, but the shortcuts keep pointing at the newer $($Newest.Version)."
    }
    Write-Host "INSTALL OK: Lianiq $Version at $Target"
}

if ($MyInvocation.InvocationName -ne '.') {
    Install-LianiqRelease
}
