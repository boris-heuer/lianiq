#Requires -Version 5.1
<#
.SYNOPSIS
    Builds the native-e2e Windows 11 VM image on the PO workstation (CAP-0174).

.DESCRIPTION
    PO step, run as administrator once and again before the 90-day evaluation ends
    (docs/native-e2e-setup.md; with -LicenceSource key only once). The host downloads every
    input first: the Python 3.12
    installer, the hash-locked wheels of requirements-lock.txt and
    native_e2e/requirements-native-lock.txt, the models (scripts/download_models.py) and the
    GitHub Actions runner package and the pinned MinGit; the PO supplies the ISO and the VB-Cable package. The
    image is applied offline to a new VHDX together with these inputs and
    guest/autounattend.xml; the guest then provisions itself (guest/provision.ps1) and shuts
    down. The script creates the internal switch without NAT, the host proxy firewall rule
    and the VM adapter ACLs, takes checkpoint 'clean' and prints the image id and builds to
    record (S-04).

    Activation (contract 7.4) is the only network of the build: while the guest runs, the
    host runs egress-proxy.py once with the build-only activation-allowlist.txt; the guest
    points its WinHTTP proxy at it, activates online, resets the WinHTTP proxy and only
    then finishes. The proxy is stopped before checkpoint 'clean', also on failure.

.PARAMETER LicenceSource
    'evaluation' (default): the Windows 11 Enterprise evaluation ISO; image.json records
    licence_expires. 'key': a licensed (non-evaluation) ISO of the key's edition; the PO
    types the key on the VM console when the guest opens the product key window. The key
    is never a script argument and never written to a log, image.json or a receipt.

.EXAMPLE
    .\tools\native-e2e\host\New-NativeE2eImage.ps1 -IsoPath D:\iso\win11-eval.iso `
        -VbCablePackage D:\downloads\VBCABLE_Driver_Pack45.zip
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$IsoPath,
    [Parameter(Mandatory)][string]$VbCablePackage,
    [ValidateSet('evaluation', 'key')][string]$LicenceSource = 'evaluation',
    [string]$VmName = 'lianiq-native-e2e',
    [string]$StateRoot = (Join-Path $env:ProgramData 'lianiq-native-e2e'),
    [string]$SwitchName = 'lianiq-e2e',
    [string]$HostAddress = '192.168.250.1',
    [string]$GuestAddress = '192.168.250.10',
    [ValidateRange(16, 30)][int]$PrefixLength = 24,
    [ValidateRange(1024, 65535)][int]$ProxyPort = 8080,
    [int]$ImageIndex = 0,
    [ValidateRange(64, 512)][int]$DiskSizeGB = 128,
    [int]$ProvisionTimeoutMinutes = 180,
    [switch]$Replace
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
. (Join-Path $PSScriptRoot 'NativeE2e.Host.ps1')
. (Join-Path $PSScriptRoot 'NativeE2e.Image.ps1')

# Python 3.12.10 is the last 3.12 release with a Windows installer. python.org publishes no
# SHA-256 for it, so the download is checked by size and a valid PSF Authenticode signature,
# and its SHA-256 is recorded in image.json.
$PythonVersion = '3.12.10'
$PythonUrl = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe'
$PythonSize = 26964224

# MinGit gives the guest the git that S-01 and actions/checkout need. The release, asset and
# SHA-256 are pinned; the download must match both the pin and the release asset digest.
$MinGitTag = 'v2.56.0.windows.4'
$MinGitVersion = $MinGitTag.TrimStart('v')
$MinGitAsset = 'MinGit-2.56.0.4-64-bit.zip'
$MinGitUrl = 'https://github.com/git-for-windows/git/releases/download/v2.56.0.windows.4/MinGit-2.56.0.4-64-bit.zip'
$MinGitSha256 = 'e3bf78351fe777fba47ddee5950082f8a98bb0f02604fdc7ba3ee2cb68ffa877'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$RepoPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$GuestDir = Join-Path $RepoRoot 'tools\native-e2e\guest'

function Assert-Prerequisites {
    Assert-NativeE2eAdministrator
    foreach ($path in $IsoPath, $VbCablePackage) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "File not found: $path" }
    }
    if (-not (Test-Path -LiteralPath $RepoPython)) {
        throw "Run scripts\setup.ps1 in $RepoRoot first; it creates .venv with the locked set."
    }
    $check = & $RepoPython -c "import struct, sys; print(sys.version_info[:2] == (3, 12) and struct.calcsize('P') == 8)"
    if ($check -ne 'True') { throw '.venv must be 64-bit Python 3.12.' }
    foreach ($tool in 'gh', 'git') {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool is not on PATH." }
    }
    Assert-NativeE2eGhLogin
    $existing = Get-VM -Name $VmName -ErrorAction SilentlyContinue
    if ($null -ne $existing -and -not $Replace) {
        throw "VM $VmName exists. Rebuild with -Replace (it deletes the old VM and its disk)."
    }
}

function Get-PythonInstaller([string]$Payload) {
    $file = Join-Path $Payload "python-$PythonVersion-amd64.exe"
    Invoke-WebRequest -Uri $PythonUrl -OutFile $file -UseBasicParsing
    $signature = Get-AuthenticodeSignature -LiteralPath $file
    if ((Get-Item -LiteralPath $file).Length -ne $PythonSize -or $signature.Status -ne 'Valid' -or
        $signature.SignerCertificate.Subject -notlike '*Python Software Foundation*') {
        throw 'The Python installer failed its size or signature check.'
    }
    return [ordered]@{ file = Split-Path $file -Leaf; version = $PythonVersion; sha256 = Get-NativeE2eSha256 $file }
}

function Get-RunnerPackage([string]$Payload) {
    $release = Invoke-NativeE2eGh @('api', 'repos/actions/runner/releases/latest') | ConvertFrom-Json
    $asset = @($release.assets | Where-Object { $_.name -match '^actions-runner-win-x64-[0-9.]+\.zip$' })
    if ($asset.Count -ne 1 -or [string]$asset[0].digest -notmatch '^sha256:[0-9a-f]{64}$') {
        throw 'The runner release has no single win-x64 asset with a SHA-256 digest.'
    }
    Invoke-NativeE2eGh @('release', 'download', $release.tag_name, '--repo', 'actions/runner',
        '--pattern', $asset[0].name, '--dir', $Payload) | Out-Null
    $file = Join-Path $Payload $asset[0].name
    $sha = Get-NativeE2eSha256 $file
    if ("sha256:$sha" -ne $asset[0].digest) { throw 'The runner package digest does not match.' }
    return [ordered]@{ file = $asset[0].name; version = $release.tag_name.TrimStart('v'); sha256 = $sha }
}

function Get-MinGitPackage([string]$Payload) {
    $release = Invoke-NativeE2eGh @('api', ('repos/git-for-windows/git/releases/tags/' + $MinGitTag)) | ConvertFrom-Json
    $asset = @($release.assets | Where-Object { $_.name -ceq $MinGitAsset })
    if ($asset.Count -ne 1 -or [string]$asset[0].digest -cne "sha256:$MinGitSha256" -or
        [string]$asset[0].browser_download_url -cne $MinGitUrl) {
        throw "The MinGit release $MinGitTag has no single $MinGitAsset with the pinned SHA-256 digest."
    }
    Invoke-NativeE2eGh @('release', 'download', $MinGitTag, '--repo', 'git-for-windows/git',
        '--pattern', $MinGitAsset, '--dir', $Payload) | Out-Null
    $sha = Get-NativeE2eSha256 (Join-Path $Payload $MinGitAsset)
    if ($sha -cne $MinGitSha256) { throw 'The MinGit package does not match its pinned SHA-256.' }
    return [ordered]@{ file = $MinGitAsset; version = $MinGitVersion; sha256 = $sha }
}

function Get-Wheels([string]$Payload) {
    Copy-Item -LiteralPath (Join-Path $RepoRoot 'requirements-lock.txt') -Destination $Payload
    Copy-Item -LiteralPath (Join-Path $RepoRoot 'native_e2e\requirements-native-lock.txt') -Destination $Payload
    & $RepoPython -m pip download --only-binary=:all: --no-deps --require-hashes `
        -r (Join-Path $Payload 'requirements-lock.txt') `
        -r (Join-Path $Payload 'requirements-native-lock.txt') -d (Join-Path $Payload 'wheels')
    if ($LASTEXITCODE -ne 0) { throw 'pip download of the locked wheels failed.' }
}

function Get-Models([string]$Payload) {
    & $RepoPython (Join-Path $RepoRoot 'scripts\download_models.py')
    if ($LASTEXITCODE -ne 0) { throw 'scripts\download_models.py failed.' }
    Copy-Item -LiteralPath (Join-Path $RepoRoot 'models') -Destination (Join-Path $Payload 'models') -Recurse
    $manifest = Join-Path $Payload 'models\model-manifest.json'
    if (-not (Test-Path -LiteralPath $manifest)) { throw 'models\model-manifest.json is missing.' }
    return Get-NativeE2eSha256 $manifest
}

function New-Unattend([string]$UiLanguage) {
    $bytes = New-Object byte[] 24
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $password = 'Build-' + ([Convert]::ToBase64String($bytes) -replace '[^A-Za-z0-9]', 'x')
    $template = Get-Content -LiteralPath (Join-Path $GuestDir 'autounattend.xml') -Raw -Encoding UTF8
    return $template.Replace('@@ADMIN_PASSWORD@@', $password).Replace('@@UI_LANGUAGE@@', $UiLanguage).
        Replace('@@COMPUTER_NAME@@', 'LIANIQ-E2E')
}

Assert-Prerequisites
$imageId = '{0}-{1}' -f (Get-Date).ToUniversalTime().ToString('yyyyMMdd'), ([guid]::NewGuid().ToString('N').Substring(0, 6))
$payload = Join-Path $StateRoot "downloads\$imageId"
$vmRoot = Join-Path $StateRoot 'vm'
$vhdPath = Join-Path $vmRoot "$VmName.vhdx"
New-Item -ItemType Directory -Path $StateRoot -Force | Out-Null
# Host state (host.json, image.json, downloads, VM disk, logs): owned by Administrators,
# SYSTEM and Administrators only.
& icacls.exe $StateRoot /setowner '*S-1-5-32-544' /q | Out-Null
if ($LASTEXITCODE -ne 0) { throw "icacls /setowner failed on $StateRoot." }
& icacls.exe $StateRoot /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' /q | Out-Null
if ($LASTEXITCODE -ne 0) { throw "icacls failed on $StateRoot." }
New-Item -ItemType Directory -Path $payload, $vmRoot -Force | Out-Null
Write-NativeE2eStep "Image $imageId; inputs go to $payload"

Write-NativeE2eStep 'Downloading Python, wheels, models, the runner and MinGit on the host'
$python = Get-PythonInstaller $payload
Get-Wheels $payload
$modelsSha = Get-Models $payload
$runner = Get-RunnerPackage $payload
$minGit = Get-MinGitPackage $payload
$vbFile = Split-Path $VbCablePackage -Leaf
Copy-Item -LiteralPath $VbCablePackage -Destination (Join-Path $payload $vbFile)
foreach ($guestScript in 'provision.ps1', 'admin-helper.ps1', 'runner-logon.ps1') {
    Copy-Item -LiteralPath (Join-Path $GuestDir $guestScript) -Destination $payload
}
Copy-Item -LiteralPath (Join-Path $RepoRoot 'native_e2e\data\make_test_phrase.py') -Destination $payload

Write-NativeE2eStep 'Hashing the ISO'
$hostVersion = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
$commit = (& git -C $RepoRoot rev-parse HEAD).Trim()
$networkPrefix = Get-NativeE2eNetworkPrefix $HostAddress $PrefixLength
$inputs = [ordered]@{
    schema           = 'lianiq-native-e2e-build-inputs/v1'
    image_id         = $imageId
    created_utc      = (Get-Date).ToUniversalTime().ToString('o')
    host_os_build    = '{0}.{1}' -f $hostVersion.CurrentBuild, $hostVersion.UBR
    source_commit    = $commit
    licence_source   = $LicenceSource
    python_installer = $python
    runner           = $runner
    mingit           = $minGit
    vb_cable         = [ordered]@{ file = $vbFile; sha256 = Get-NativeE2eSha256 (Join-Path $payload $vbFile) }
    network          = [ordered]@{ host_address = $HostAddress; guest_address = $GuestAddress
        prefix_length = $PrefixLength; proxy_port = $ProxyPort }
    inputs           = [ordered]@{
        iso_sha256             = Get-NativeE2eSha256 $IsoPath
        python_sha256          = $python.sha256
        runner_version         = $runner.version
        runner_sha256          = $runner.sha256
        mingit_version         = $minGit.version
        mingit_sha256          = $minGit.sha256
        vb_cable_sha256        = Get-NativeE2eSha256 (Join-Path $payload $vbFile)
        requirements_lock_sha256 = Get-NativeE2eSha256 (Join-Path $payload 'requirements-lock.txt')
        native_lock_sha256     = Get-NativeE2eSha256 (Join-Path $payload 'requirements-native-lock.txt')
        models_manifest_sha256 = $modelsSha
    }
}
Write-NativeE2eJson (Join-Path $payload 'build-inputs.json') $inputs

if ($Replace -and (Get-VM -Name $VmName -ErrorAction SilentlyContinue)) {
    Write-NativeE2eStep "Removing the previous VM $VmName and its disk"
    Stop-VM -Name $VmName -TurnOff -Force -ErrorAction SilentlyContinue
    Get-VMSnapshot -VMName $VmName | Remove-VMSnapshot
    Remove-VM -Name $VmName -Force
}
if (Test-Path -LiteralPath $vhdPath) { Remove-Item -LiteralPath $vhdPath -Force }

Write-NativeE2eStep "Internal switch $SwitchName, host $HostAddress/$PrefixLength, proxy port $ProxyPort"
Set-NativeE2eSwitch $SwitchName $HostAddress $PrefixLength $GuestAddress $ProxyPort | Out-Null

$iso = Mount-DiskImage -ImagePath (Resolve-Path $IsoPath).Path -PassThru
try {
    $letter = ($iso | Get-Volume).DriveLetter
    $imageFile = @("${letter}:\sources\install.wim", "${letter}:\sources\install.esd") |
        Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $imageFile) { throw 'The ISO has no sources\install.wim or install.esd.' }
    $edition = Select-NativeE2eEdition $imageFile $ImageIndex
    Assert-NativeE2eLicenceMedia $LicenceSource $edition
    $language = @($edition.Languages)[0]
    if (-not $language) { $language = 'en-US' }
    New-NativeE2eSystemDisk $vhdPath $DiskSizeGB $imageFile $edition (New-Unattend $language) $payload
} finally {
    Dismount-DiskImage -ImagePath (Resolve-Path $IsoPath).Path | Out-Null
}

New-NativeE2eVm $VmName $vhdPath $vmRoot $SwitchName $HostAddress $ProxyPort
$hostPython = (& $RepoPython -c 'import sys; print(sys._base_executable)').Trim()
$logDir = Join-Path $StateRoot "logs\$imageId"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$activationProxy = $null
try {
    # Build-only activation egress (contract 7.4): the adapter ACLs are already in place and
    # the guest reaches only this proxy, which relays only to the activation hosts.
    Write-NativeE2eStep 'Starting the build-only activation proxy'
    $activationProxy = Start-NativeE2eEgressProxy $hostPython $HostAddress $ProxyPort `
        (Join-Path $PSScriptRoot 'activation-allowlist.txt') (Join-Path $logDir 'activation-proxy.log')
    Write-NativeE2eStep 'Starting the guest; it provisions itself, activates Windows and shuts down.'
    Write-NativeE2eStep 'If VB-Cable asks to trust the driver publisher, confirm it in the VM console (Hyper-V Manager > Connect).'
    if ($LicenceSource -eq 'key') {
        Write-NativeE2eStep 'PO step: when the guest opens the product key window, type your key in the VM console (Hyper-V Manager > Connect). Never paste it anywhere else.'
    }
    Start-VM -Name $VmName
    Wait-NativeE2eCondition { (Get-VM -Name $VmName).State -eq 'Off' } ($ProvisionTimeoutMinutes * 60) 30 'guest provisioning'
} finally {
    Stop-NativeE2eEgressProxy $activationProxy
    Write-NativeE2eStep 'Activation proxy stopped'
}

$imageJson = Read-NativeE2eProvisionResult $vhdPath $logDir
$image = $imageJson | ConvertFrom-Json
if ([string]$image.activation -ne 'activated' -or [string]$image.licence_source -ne $LicenceSource) {
    throw "Windows is not activated (image.json activation '$($image.activation)'); see docs/native-e2e-setup.md."
}
[IO.File]::WriteAllText((Join-Path $StateRoot 'image.json'), $imageJson, (New-Object Text.UTF8Encoding $false))

Get-VMSnapshot -VMName $VmName | Remove-VMSnapshot
Checkpoint-VM -Name $VmName -SnapshotName $script:NativeE2eCheckpoint
Write-NativeE2eJson (Join-Path $StateRoot 'host.json') ([ordered]@{
        schema = 'lianiq-native-e2e-host/v1'; image_id = $imageId; vm_name = $VmName
        switch_name = $SwitchName; host_address = $HostAddress; guest_address = $GuestAddress
        network_prefix = $networkPrefix; prefix_length = $PrefixLength; proxy_port = $ProxyPort
        host_python = $hostPython; repo_root = $RepoRoot
    })
foreach ($bulk in 'wheels', 'models') {
    Remove-Item -LiteralPath (Join-Path $payload $bulk) -Recurse -Force -ErrorAction SilentlyContinue
}

Write-NativeE2eStep "Checkpoint '$($script:NativeE2eCheckpoint)' taken. Record these values (S-04):"
Write-Host "  image id:        $($image.image_id) ($($image.image))"
Write-Host "  Windows build:   $($image.windows_build) ($($image.windows_edition))"
Write-Host "  host OS build:   $($image.host_os_build)"
Write-Host "  licence:         $($image.licence_source), $($image.activation)"
if ($LicenceSource -eq 'evaluation') { Write-Host "  licence expires: $($image.licence_expires) (rebuild before then)" }
Write-Host "  test phrase:     $($image.test_phrase.sha256)"
Write-Host "  models manifest: $($image.models_manifest_sha256)"
