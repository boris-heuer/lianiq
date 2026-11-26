#Requires -Version 5.1
<#
.SYNOPSIS
    Offline provisioning of the native-e2e guest at image build (CAP-0174, contract 4.4).

.DESCRIPTION
    Runs once as the built-in Administrator (answer file FirstLogonCommands) on the inputs
    New-NativeE2eImage.ps1 copied to C:\ProgramData\lianiq-e2e\setup; no network except
    activation. Installs the VC++ runtime, Python, wheels, models, VB-Cable (with
    -VbCableAbPackage also VB-Cable A+B), the test phrase, the runner, MinGit, the admin
    helper, the logon task and WFP auditing; creates the non-admin auto-logon user 'e2e',
    activates Windows via the host's build-only proxy (activation.ps1), writes image.json,
    disables the build account, deletes the answer file and shuts down.
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
$MinGitDir = Join-Path $Root 'mingit'
$GitExe = Join-Path $MinGitDir 'cmd\git.exe'
$TestUser = 'e2e'
$SidSystem = '*S-1-5-18'
$SidAdministrators = '*S-1-5-32-544'
$SidUsers = '*S-1-5-32-545'
# Audit subcategory "Filtering Platform Connection" (events 5156/5157), locale independent.
$WfpConnectionAudit = '{0CCE9226-69AE-11D9-BED3-505054503030}'
$script:Step = 'start'
. (Join-Path $PSScriptRoot 'activation.ps1')

function Invoke-Step([string]$Name, [scriptblock]$Body) {
    $script:Step = $Name
    Write-Host "== $Name"
    & $Body
}

function Invoke-Native([string]$FilePath, [string[]]$Arguments) {
    Invoke-NativeCaptured $FilePath $FilePath $Arguments | Out-Null
}

function Invoke-NativeCaptured([string]$Name, [string]$FilePath, [string[]]$Arguments) {
    # stdout and stderr reach provision.log (5.1 needs Continue).
    $ErrorActionPreference = 'Continue'
    $output = @(& $FilePath @Arguments 2>&1 | ForEach-Object { "$_" })
    $output | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw ("$Name exited with code ${LASTEXITCODE}: " + (($output | Select-Object -Last 4) -join ' | '))
    }
    return $output
}

function Invoke-Netsh([string[]]$Arguments) {
    # Native: a local 'Continue' keeps its output from turning into errors.
    $ErrorActionPreference = 'Continue'
    & netsh.exe @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "netsh $($Arguments -join ' ') exited with code $LASTEXITCODE" }
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

function Get-ActiveEndpointName([string]$Flow) {
    # PKEY_Device_DeviceDesc of each active endpoint; as in the app, one without it is skipped.
    $base = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\$Flow"
    foreach ($endpoint in @(Get-ChildItem -LiteralPath $base -ErrorAction SilentlyContinue)) {
        try {
            $state = Get-ItemPropertyValue -LiteralPath $endpoint.PSPath -Name 'DeviceState'
            if (-not ($state -band 1)) { continue }
            Get-ItemPropertyValue -LiteralPath (Join-Path $endpoint.PSPath 'Properties') `
                -Name '{a45c254e-df1c-4efd-8020-67d146a850e0},2'
        } catch { }
    }
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
        # New profiles copy the default hive: 100 % scale, no screen saver, no notifications.
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
        foreach ($folder in 'bin', 'models', 'admin\requests', 'admin\results', 'jit', 'state') {
            New-Item -ItemType Directory -Path (Join-Path $Root $folder) -Force | Out-Null
        }
        # Users read the root; only SYSTEM and Administrators write it.
        Set-ExclusiveAcl $Root @("${SidSystem}:(OI)(CI)F", "${SidAdministrators}:(OI)(CI)F", "${SidUsers}:(OI)(CI)RX")
        foreach ($writable in 'admin\requests', 'jit', 'state') {
            Invoke-Native 'icacls.exe' @((Join-Path $Root $writable), '/grant', "${TestUser}:(OI)(CI)M", '/q')
        }
        foreach ($guestScript in 'admin-helper.ps1', 'runner-logon.ps1') {
            Copy-Item -LiteralPath (Join-Path $Setup $guestScript) -Destination $Bin -Force
        }
    }

    Invoke-Step 'vc-redist' {
        # For onnxruntime. 3010: restart pending; 1638: newer present.
        $redist = Join-Path $Setup $inputs.vc_redist.file
        Assert-Signed $redist
        $process = Start-Process -FilePath $redist -ArgumentList @('/install', '/quiet', '/norestart') -Wait -PassThru
        if (@(0, 1638, 3010) -notcontains $process.ExitCode) { throw "VC++ runtime installer exited with $($process.ExitCode)." }
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
        # The job installs the checkout here (no network).
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
        # Names the app reads (lianiq.audio.windows_endpoints), not PnP names.
        $deadline = (Get-Date).AddMinutes(5)
        do {
            $render = @(Get-ActiveEndpointName 'Render')
            $capture = @(Get-ActiveEndpointName 'Capture')
            $found = ($render -ccontains 'CABLE Input') -and ($capture -ccontains 'CABLE Output')
            if (-not $found) { Start-Sleep -Seconds 5 }
        } while (-not $found -and (Get-Date) -lt $deadline)
        if (-not $found) {
            throw ("VB-Cable endpoints CABLE Input and CABLE Output are missing (active render: '" +
                ($render -join "', '") + "'; active capture: '" + ($capture -join "', '") + "').")
        }
    }

    if ($null -ne $inputs.vb_cable_ab) {
        # Optional (-VbCableAbPackage): cables A and B for the Call Bridge rows E-34..E-38,
        # installed like VB-Cable. Without the package this step does not run.
        Invoke-Step 'vb-cable-ab' {
            $package = Join-Path $Setup 'vbcable-ab'
            Expand-Archive -LiteralPath (Join-Path $Setup $inputs.vb_cable_ab.file) -DestinationPath $package -Force
            $setupExes = @(Get-ChildItem -LiteralPath $package -Recurse -File -Filter 'VBCABLE_*Setup_x64.exe')
            if ($setupExes.Count -eq 0) { throw 'The VB-Cable A+B package holds no VBCABLE_*Setup_x64.exe.' }
            Write-Host 'Installing VB-Cable A+B. If Windows asks to trust the driver publisher, confirm it in the VM console.'
            foreach ($setupExe in $setupExes) {
                Assert-Signed $setupExe.FullName
                Start-Process -FilePath $setupExe.FullName -ArgumentList @('-i', '-h') -Wait | Out-Null
            }
            # The endpoint names the rows read (native_e2e.context.CABLE_AB_NAMES).
            $deadline = (Get-Date).AddMinutes(5)
            do {
                $render = @(Get-ActiveEndpointName 'Render')
                $capture = @(Get-ActiveEndpointName 'Capture')
                $missing = @(foreach ($cable in 'A', 'B') {
                        if ($render -cnotcontains "CABLE-$cable Input") { "CABLE-$cable Input" }
                        if ($capture -cnotcontains "CABLE-$cable Output") { "CABLE-$cable Output" }
                    })
                if ($missing.Count -gt 0) { Start-Sleep -Seconds 5 }
            } while ($missing.Count -gt 0 -and (Get-Date) -lt $deadline)
            if ($missing.Count -gt 0) {
                throw ("VB-Cable A+B endpoints are missing: '" + ($missing -join "', '") + "'.")
            }
            Remove-Item -LiteralPath $package, (Join-Path $Setup $inputs.vb_cable_ab.file) -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    $phrase = $null
    Invoke-Step 'test-phrase' {
        $venvPython = Join-Path $Venv 'Scripts\python.exe'
        $voice = Join-Path $Models 'piper\de_DE-thorsten-medium.onnx'
        $wav = Join-Path $Root 'test-phrase.wav'
        $output = @(Invoke-NativeCaptured 'make_test_phrase.py' $venvPython @('-I',
                (Join-Path $Setup 'make_test_phrase.py'), '--voice', $voice, '--output', $wav))
        $script:phrase = ($output | Where-Object { $_ -like '{*' } | Select-Object -Last 1) | ConvertFrom-Json
        if ($script:phrase.sha256 -ne (Get-FileSha256 $wav)) { throw 'Test phrase hash mismatch.' }
    }

    Invoke-Step 'runner' {
        Expand-Archive -LiteralPath (Join-Path $Setup $inputs.runner.file) -DestinationPath $RunnerDir -Force
        Invoke-Native 'icacls.exe' @($RunnerDir, '/grant', "${TestUser}:(OI)(CI)M", '/q')
    }

    Invoke-Step 'mingit' {
        # Offline, on no PATH; the inherited root ACL lets the test user run, not change, it.
        $package = Join-Path $Setup $inputs.mingit.file
        if ((Get-FileSha256 $package) -cne $inputs.mingit.sha256) {
            throw 'The MinGit package does not match the SHA-256 in build-inputs.json.'
        }
        Expand-Archive -LiteralPath $package -DestinationPath $MinGitDir -Force
        $reported = (& $GitExe --version | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or $reported -cne "git version $($inputs.mingit.version)") {
            throw "MinGit reports '$reported', expected git version $($inputs.mingit.version)."
        }
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
        # Build-only egress (contract 7.4), activation hosts only; activation reads WinHTTP.
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
            git                    = $GitExe
            git_version            = $inputs.mingit.version
            https_proxy            = [Environment]::GetEnvironmentVariable('https_proxy', 'Machine')
            inputs                 = $inputs.inputs
        }
        if ($inputs.licence_source -eq 'evaluation') { $image['licence_expires'] = $script:licence.Expires }
        Write-Json (Join-Path $Root 'image.json') $image
    }

    Invoke-Step 'cleanup' {
        foreach ($item in 'wheels', 'models', 'vbcable', $inputs.python_installer.file, $inputs.vc_redist.file,
            $inputs.vb_cable.file, $inputs.runner.file, $inputs.mingit.file) {
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
