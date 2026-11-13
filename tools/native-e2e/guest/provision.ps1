#Requires -Version 5.1
<#
.SYNOPSIS
    Offline provisioning of the native-e2e guest at image build (CAP-0174, contract 4.4).

.DESCRIPTION
    Runs once as the built-in Administrator from the answer file's FirstLogonCommands.
    New-NativeE2eImage.ps1 has copied every input into C:\ProgramData\lianiq-e2e\setup
    beforehand; the guest has no network except the activation step. The script installs Python 3.12 for all users,
    the hash-locked wheels into the image environment, the read-only models, VB-Cable (one
    cable), the N-01 test phrase, the GitHub Actions runner package (not a service), the
    SYSTEM admin helper, the e2e logon task and WFP auditing; it creates the non-admin
    auto-logon user 'e2e', activates Windows online through the host's build-only
    activation proxy (WinHTTP proxy set, then reset in a finally path; for the licence
    source 'key' the PO types the key into the product key window on the VM console),
    writes image.json, disables the build account, deletes the answer file and shuts the
    guest down. The host then takes checkpoint 'clean'.
    The outcome is written to setup\provision-result.json for the host to read.
#>
[CmdletBinding()]
param(
    [string]$Root = 'C:\ProgramData\lianiq-e2e'
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Setup = Join-Path $Root 'setup'
$Bin = Join-Path $Root 'bin'
$Models = Join-Path $Root 'models'
$Venv = Join-Path $Root 'venv'
$PythonDir = 'C:\Program Files\Python312'
$Interpreter = Join-Path $PythonDir 'python.exe'
$RunnerDir = 'C:\actions-runner'
$TestUser = 'e2e'
$SidSystem = '*S-1-5-18'
$SidAdministrators = '*S-1-5-32-544'
$SidUsers = '*S-1-5-32-545'
# Audit subcategory "Filtering Platform Connection" (events 5156/5157), locale independent.
$WfpConnectionAudit = '{0CCE9226-69AE-11D9-BED3-505054503030}'
# Application id of Windows in the Software Licensing Service.
$WindowsAppId = '55c92734-d682-4d71-983e-d6ec3f16059f'
$script:Step = 'start'

function Invoke-Step([string]$Name, [scriptblock]$Body) {
    $script:Step = $Name
    Write-Host "== $Name"
    & $Body
}

function Invoke-Native([string]$FilePath, [string[]]$Arguments) {
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$FilePath exited with code $LASTEXITCODE" }
}

function Invoke-Netsh([string[]]$Arguments) {
    # netsh is native: a local 'Continue' keeps its output from turning into errors.
    $ErrorActionPreference = 'Continue'
    & netsh.exe @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "netsh $($Arguments -join ' ') exited with code $LASTEXITCODE" }
}

function Get-WindowsLicence {
    # The installed Windows licence. Only status, channel and grace period are read; the
    # product key, or any part of it, is never read, logged or recorded.
    $filter = "ApplicationID='$WindowsAppId' AND LicenseIsAddon=False AND PartialProductKey IS NOT NULL"
    $products = @(Get-CimInstance -ClassName SoftwareLicensingProduct -Filter $filter)
    if ($products.Count -ne 1) { throw "Expected one installed Windows licence, found $($products.Count)." }
    return $products[0]
}

function Invoke-GuestActivation([string]$Source) {
    $isEvaluation = [string](Get-WindowsLicence).Description -like '*TIMEBASED_EVAL*'
    if (($Source -eq 'evaluation') -ne $isEvaluation) {
        throw "The installed edition does not match the licence source '$Source'."
    }
    $minutes = 10
    if ($Source -eq 'key') {
        $minutes = 60
        Write-Host 'PO step: type your product key in the window that opens (VM console). It is never logged.'
        Start-Process -FilePath 'slui.exe' -ArgumentList '3'
    }
    $deadline = (Get-Date).AddMinutes($minutes)
    $lastError = 'no attempt'
    do {
        try {
            $call = Invoke-CimMethod -InputObject (Get-WindowsLicence) -MethodName Activate
            $lastError = "Activate returned $($call.ReturnValue)"
            $product = Get-WindowsLicence
            if ($call.ReturnValue -eq 0 -and $product.LicenseStatus -eq 1) { break }
        } catch {
            $lastError = $_.Exception.Message
        }
        Start-Sleep -Seconds 30
    } while ((Get-Date) -lt $deadline)
    $product = Get-WindowsLicence
    if ($product.LicenseStatus -ne 1) {
        throw ("Online activation failed ($lastError). First suspect: a CRL/OCSP fetch over plain " +
            'HTTP, which the CONNECT-only proxy refuses; see activation-proxy.log on the host.')
    }
    $expires = $null
    if ($Source -eq 'evaluation') {
        $grace = [int64]$product.GracePeriodRemaining
        if ($grace -le 0) { throw 'The evaluation licence reports no remaining time.' }
        $expires = [DateTime]::UtcNow.AddMinutes($grace).ToString('yyyy-MM-ddTHH:mm:ssZ')
    }
    return [pscustomobject]@{ Result = 'activated'; Expires = $expires }
}

function Set-ExclusiveAcl([string]$Path, [string[]]$Grants) {
    Invoke-Native 'icacls.exe' (@($Path, '/inheritance:r', '/grant:r') + $Grants + @('/q'))
}

function New-RandomPassword {
    $bytes = New-Object byte[] 24
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return 'E2e-' + ([Convert]::ToBase64String($bytes) -replace '[^A-Za-z0-9]', 'x')
}

function Set-RegistryValue([string]$Path, [string]$Name, $Value, [string]$Type = 'DWord') {
    if (-not (Test-Path -LiteralPath $Path)) { New-Item -Path $Path -Force | Out-Null }
    New-ItemProperty -LiteralPath $Path -Name $Name -Value $Value -PropertyType $Type `
        -Force | Out-Null
}

function Get-FileSha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Write-Json([string]$Path, $Value) {
    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 6),
        (New-Object Text.UTF8Encoding $false))
}

function Assert-Signed([string]$Path) {
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne 'Valid') { throw "Authenticode signature is not valid: $Path" }
}

$inputs = Get-Content -LiteralPath (Join-Path $Setup 'build-inputs.json') -Raw | ConvertFrom-Json
Start-Transcript -LiteralPath (Join-Path $Setup 'provision.log') -Append | Out-Null
try {
    $identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    if (-not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'provision.ps1 must run elevated.'
    }

    Invoke-Step 'quiet-desktop' {
        Set-RegistryValue 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\Personalization' 'NoLockScreen' 1
        Set-RegistryValue 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\OOBE' 'DisablePrivacyExperience' 1
        Set-RegistryValue 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon' 'EnableFirstLogonAnimation' 0
        Set-RegistryValue 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU' 'NoAutoUpdate' 1
        $ts = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services'
        Set-RegistryValue $ts 'fDisableClip' 1
        Set-RegistryValue $ts 'fDisableCdm' 1
        foreach ($setting in 'standby-timeout-ac', 'monitor-timeout-ac', 'hibernate-timeout-ac') {
            Invoke-Native 'powercfg.exe' @('/change', $setting, '0')
        }
        Invoke-Native 'powercfg.exe' @('/hibernate', 'off')
        Set-Service -Name 'Audiosrv' -StartupType Automatic
    }

    Invoke-Step 'default-user-profile' {
        # New profiles (the e2e user signs in after the revert) copy the default hive:
        # 100 % scale, no screen saver, no toast notifications or notification centre.
        Invoke-Native 'reg.exe' @('load', 'HKU\E2eDefault', 'C:\Users\Default\NTUSER.DAT')
        try {
            $hive = 'Registry::HKEY_USERS\E2eDefault'
            Set-RegistryValue "$hive\Control Panel\Desktop" 'LogPixels' 96
            Set-RegistryValue "$hive\Control Panel\Desktop" 'Win8DpiScaling' 1
            Set-RegistryValue "$hive\Control Panel\Desktop" 'ScreenSaveActive' '0' 'String'
            Set-RegistryValue "$hive\Software\Microsoft\Windows\CurrentVersion\PushNotifications" 'ToastEnabled' 0
            Set-RegistryValue "$hive\Software\Policies\Microsoft\Windows\Explorer" 'DisableNotificationCenter' 1
        } finally {
            [GC]::Collect()
            Invoke-Native 'reg.exe' @('unload', 'HKU\E2eDefault')
        }
    }

    Invoke-Step 'network' {
        $adapters = @(Get-NetAdapter | Where-Object { $_.HardwareInterface })
        if ($adapters.Count -ne 1) { throw "Expected one network adapter, found $($adapters.Count)." }
        $alias = $adapters[0].Name
        Get-NetIPAddress -InterfaceAlias $alias -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Remove-NetIPAddress -Confirm:$false
        # No gateway and no DNS server: the only reachable endpoint is the host proxy.
        New-NetIPAddress -InterfaceAlias $alias -IPAddress $inputs.network.guest_address `
            -PrefixLength $inputs.network.prefix_length | Out-Null
        Set-DnsClientServerAddress -InterfaceAlias $alias -ResetServerAddresses
        $proxy = 'http://{0}:{1}' -f $inputs.network.host_address, $inputs.network.proxy_port
        [Environment]::SetEnvironmentVariable('https_proxy', $proxy, 'Machine')
    }

    Invoke-Step 'test-user' {
        $password = New-RandomPassword
        $secure = ConvertTo-SecureString $password -AsPlainText -Force
        New-LocalUser -Name $TestUser -Password $secure -PasswordNeverExpires `
            -UserMayNotChangePassword -AccountNeverExpires -Description 'native-e2e test user' | Out-Null
        Add-LocalGroupMember -SID 'S-1-5-32-545' -Member $TestUser -ErrorAction SilentlyContinue
        $admins = @(Get-LocalGroupMember -SID 'S-1-5-32-544' | Where-Object { $_.Name -like "*\$TestUser" })
        if ($admins.Count -ne 0) { throw 'The test user must not be an administrator.' }
        $winlogon = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
        Set-RegistryValue $winlogon 'AutoAdminLogon' '1' 'String'
        Set-RegistryValue $winlogon 'DefaultUserName' $TestUser 'String'
        Set-RegistryValue $winlogon 'DefaultDomainName' $env:COMPUTERNAME 'String'
        Set-RegistryValue $winlogon 'DefaultPassword' $password 'String'
        Remove-ItemProperty -LiteralPath $winlogon -Name 'AutoLogonCount' -ErrorAction SilentlyContinue
    }

    Invoke-Step 'folders' {
        foreach ($folder in $Bin, $Models, 'admin\requests', 'admin\results', 'jit', 'state') {
            New-Item -ItemType Directory -Path (Join-Path $Root $folder) -Force | Out-Null
        }
        # Users read the root; only SYSTEM and Administrators write it (bin, models, image.json).
        Set-ExclusiveAcl $Root @("${SidSystem}:(OI)(CI)F", "${SidAdministrators}:(OI)(CI)F", "${SidUsers}:(OI)(CI)RX")
        foreach ($writable in 'admin\requests', 'jit', 'state') {
            Invoke-Native 'icacls.exe' @((Join-Path $Root $writable), '/grant', "${TestUser}:(OI)(CI)M", '/q')
        }
        foreach ($guestScript in 'admin-helper.ps1', 'runner-logon.ps1') {
            Copy-Item -LiteralPath (Join-Path $Setup $guestScript) -Destination $Bin -Force
        }
    }

    Invoke-Step 'python' {
        $installer = Join-Path $Setup $inputs.python_installer.file
        Assert-Signed $installer
        $arguments = @('/quiet', 'InstallAllUsers=1', 'PrependPath=0', 'Include_launcher=0',
            'Include_test=0', 'Include_doc=0', 'Shortcuts=0', "TargetDir=`"$PythonDir`"")
        $process = Start-Process -FilePath $installer -ArgumentList $arguments -Wait -PassThru
        if ($process.ExitCode -ne 0) { throw "Python installer exited with $($process.ExitCode)." }
        Invoke-Native $Interpreter @('-m', 'venv', $Venv)
        $venvPython = Join-Path $Venv 'Scripts\python.exe'
        Invoke-Native $venvPython @('-m', 'pip', 'install', '--no-index', '--find-links',
            (Join-Path $Setup 'wheels'), '--require-hashes',
            '-r', (Join-Path $Setup 'requirements-lock.txt'),
            '-r', (Join-Path $Setup 'requirements-native-lock.txt'))
        Invoke-Native $venvPython @('-m', 'pip', 'check')
        # The job installs the checked-out project into this environment (no network).
        Invoke-Native 'icacls.exe' @($Venv, '/grant', "${TestUser}:(OI)(CI)M", '/q')
    }

    Invoke-Step 'models' {
        Copy-Item -Path (Join-Path $Setup 'models\*') -Destination $Models -Recurse -Force
        Set-ExclusiveAcl $Models @("${SidSystem}:(OI)(CI)F", "${SidAdministrators}:(OI)(CI)F", "${SidUsers}:(OI)(CI)RX")
    }

    Invoke-Step 'vb-cable' {
        $package = Join-Path $Setup 'vbcable'
        Expand-Archive -LiteralPath (Join-Path $Setup $inputs.vb_cable.file) -DestinationPath $package -Force
        $setupExe = Join-Path $package 'VBCABLE_Setup_x64.exe'
        Assert-Signed $setupExe
        Write-Host 'Installing VB-Cable. If Windows asks to trust the driver publisher, confirm it in the VM console.'
        Start-Process -FilePath $setupExe -ArgumentList @('-i', '-h') -Wait | Out-Null
        $deadline = (Get-Date).AddMinutes(15)
        do {
            $endpoints = @(Get-PnpDevice -Class 'AudioEndpoint' -PresentOnly -ErrorAction SilentlyContinue |
                Where-Object { $_.FriendlyName -like 'CABLE Input*' -or $_.FriendlyName -like 'CABLE Output*' })
            if ($endpoints.Count -ge 2) { break }
            Start-Sleep -Seconds 5
        } while ((Get-Date) -lt $deadline)
        if ($endpoints.Count -lt 2) { throw 'VB-Cable endpoints CABLE Input and CABLE Output are missing.' }
    }

    $phrase = $null
    Invoke-Step 'test-phrase' {
        $venvPython = Join-Path $Venv 'Scripts\python.exe'
        $voice = Join-Path $Models 'piper\de_DE-thorsten-medium.onnx'
        $wav = Join-Path $Root 'test-phrase.wav'
        $output = & $venvPython -I (Join-Path $Setup 'make_test_phrase.py') --voice $voice --output $wav
        if ($LASTEXITCODE -ne 0) { throw 'make_test_phrase.py failed.' }
        $script:phrase = ($output | Select-Object -Last 1) | ConvertFrom-Json
        if ($script:phrase.sha256 -ne (Get-FileSha256 $wav)) { throw 'Test phrase hash mismatch.' }
    }

    Invoke-Step 'runner' {
        Expand-Archive -LiteralPath (Join-Path $Setup $inputs.runner.file) -DestinationPath $RunnerDir -Force
        Invoke-Native 'icacls.exe' @($RunnerDir, '/grant', "${TestUser}:(OI)(CI)M", '/q')
    }

    Invoke-Step 'scheduled-tasks' {
        $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
            -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        $helperAction = New-ScheduledTaskAction -Execute $powershell -Argument (
            '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}"' -f (Join-Path $Bin 'admin-helper.ps1'))
        $system = New-ScheduledTaskPrincipal -UserId 'S-1-5-18' -LogonType ServiceAccount -RunLevel Highest
        Register-ScheduledTask -TaskName 'lianiq-e2e-admin-helper' -Action $helperAction `
            -Trigger (New-ScheduledTaskTrigger -AtStartup) -Principal $system -Settings $settings -Force | Out-Null
        $logonAction = New-ScheduledTaskAction -Execute $powershell -Argument (
            '-NoProfile -ExecutionPolicy Bypass -WindowStyle Minimized -File "{0}"' -f (Join-Path $Bin 'runner-logon.ps1'))
        $account = "$env:COMPUTERNAME\$TestUser"
        $user = New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Limited
        Register-ScheduledTask -TaskName 'lianiq-e2e-runner-logon' -Action $logonAction `
            -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $account) -Principal $user -Settings $settings -Force | Out-Null
    }

    Invoke-Step 'wfp-audit' {
        Invoke-Native 'auditpol.exe' @('/set', "/subcategory:$WfpConnectionAudit", '/success:enable', '/failure:enable')
        Invoke-Native 'wevtutil.exe' @('sl', 'Security', '/ms:268435456')
    }

    $licence = $null
    Invoke-Step 'activation' {
        # Build-only egress (contract 7.4): the host proxy relays only to the activation
        # hosts now. Activation reads the WinHTTP proxy, not https_proxy.
        $winhttpProxy = '{0}:{1}' -f $inputs.network.host_address, $inputs.network.proxy_port
        try {
            Invoke-Netsh @('winhttp', 'set', 'proxy', "proxy-server=$winhttpProxy")
            $script:licence = Invoke-GuestActivation ([string]$inputs.licence_source)
        } finally {
            Invoke-Netsh @('winhttp', 'reset', 'proxy')
        }
    }

    Invoke-Step 'image-json' {
        $version = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
        $python = (& $Interpreter -c 'import platform; print(platform.python_version())').Trim()
        $image = [ordered]@{
            schema                 = 'lianiq-native-e2e-image/v1'
            image_id               = $inputs.image_id
            image                  = "win11-native-e2e@$($inputs.image_id)"
            created_utc            = $inputs.created_utc
            windows_build          = '{0}.{1}' -f $version.CurrentBuild, $version.UBR
            windows_edition        = [string]$version.EditionID
            licence_source         = [string]$inputs.licence_source
            activation             = $script:licence.Result
            host_os_build          = $inputs.host_os_build
            source_commit          = $inputs.source_commit
            python                 = $python
            interpreter            = $Interpreter
            venv                   = $Venv
            models_dir             = $Models
            models_manifest_sha256 = Get-FileSha256 (Join-Path $Models 'model-manifest.json')
            test_phrase            = [ordered]@{ path = $script:phrase.path; sha256 = $script:phrase.sha256 }
            audio                  = 'virtual (VB-Cable A)'
            test_user              = $TestUser
            runner_dir             = $RunnerDir
            https_proxy            = [Environment]::GetEnvironmentVariable('https_proxy', 'Machine')
            inputs                 = $inputs.inputs
        }
        if ($inputs.licence_source -eq 'evaluation') { $image['licence_expires'] = $script:licence.Expires }
        Write-Json (Join-Path $Root 'image.json') $image
    }

    Invoke-Step 'cleanup' {
        foreach ($item in 'wheels', 'models', 'vbcable', $inputs.python_installer.file,
            $inputs.vb_cable.file, $inputs.runner.file) {
            Remove-Item -LiteralPath (Join-Path $Setup $item) -Recurse -Force -ErrorAction SilentlyContinue
        }
        foreach ($answer in 'C:\Windows\Panther\unattend.xml', 'C:\Windows\Panther\Unattend') {
            Remove-Item -LiteralPath $answer -Recurse -Force -ErrorAction SilentlyContinue
        }
        Get-LocalUser | Where-Object { $_.SID.Value -like 'S-1-5-21-*-500' } | Disable-LocalUser
    }

    Write-Json (Join-Path $Setup 'provision-result.json') ([ordered]@{ status = 'ok'; step = $script:Step })
} catch {
    Write-Host "Provisioning failed in step $($script:Step): $($_.Exception.Message)"
    Write-Json (Join-Path $Setup 'provision-result.json') ([ordered]@{
            status = 'failed'; step = $script:Step; message = $_.Exception.Message })
} finally {
    Stop-Transcript | Out-Null
    Stop-Computer -Force
}
