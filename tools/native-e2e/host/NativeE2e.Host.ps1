#Requires -Version 5.1
# Shared helpers of the native-e2e host scripts (CAP-0174). Dot-sourced by
# New-NativeE2eImage.ps1 and Invoke-NativeE2eRun.ps1; it changes nothing on its own.

Set-StrictMode -Version 3.0

$script:NativeE2eRepository = 'boris-heuer/lianiq'
$script:NativeE2eRunnerLabels = @('self-hosted', 'windows', 'win11-native-e2e')
$script:NativeE2eGuestRoot = 'C:\ProgramData\lianiq-e2e'
$script:NativeE2eCheckpoint = 'clean'
# Integration service ids (the display names are localised on non-English hosts).
$script:NativeE2eGuestServiceId = '6C09BB55-D683-4DA0-8931-C9BF705F6480'
$script:NativeE2eHeartbeatId = '84EAAE65-2F2E-45F5-9BB5-0E857DC8EB47'

function Write-NativeE2eStep([string]$Message) {
    Write-Host ('[{0}] {1}' -f (Get-Date).ToString('HH:mm:ss'), $Message)
}

function Assert-NativeE2eAdministrator {
    $principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Run this script from an elevated PowerShell (Run as administrator).'
    }
    if (-not (Get-Command -Name 'New-VM' -ErrorAction SilentlyContinue)) {
        throw 'The Hyper-V PowerShell module is missing. Enable Hyper-V first (docs/native-e2e-setup.md).'
    }
}

function Get-NativeE2eSha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Write-NativeE2eJson([string]$Path, $Value) {
    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 6),
        (New-Object Text.UTF8Encoding $false))
}

function Read-NativeE2eHostState([string]$StateRoot) {
    $path = Join-Path $StateRoot 'host.json'
    if (-not (Test-Path -LiteralPath $path)) {
        throw "No image found ($path). Build it with New-NativeE2eImage.ps1 first."
    }
    return Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Get-NativeE2eIntegrationService([string]$VmName, [string]$Id) {
    $service = Get-VMIntegrationService -VMName $VmName |
        Where-Object { $_.Id -like "*\$Id" }
    if ($null -eq $service) { throw "Integration service $Id not found on $VmName." }
    return $service
}

function Wait-NativeE2eCondition([scriptblock]$Condition, [int]$TimeoutSeconds,
        [int]$PollSeconds, [string]$What) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while (-not (& $Condition)) {
        if ((Get-Date) -gt $deadline) { throw "Timed out after $TimeoutSeconds s: $What" }
        Start-Sleep -Seconds $PollSeconds
    }
}

function Invoke-NativeE2eGhRaw([string[]]$Arguments) {
    # The only place that runs gh. Windows PowerShell 5.1 turns redirected native stderr into
    # terminating errors under the callers' 'Stop' preference, so this function uses
    # 'Continue' and reports the exit code and both streams instead.
    $ErrorActionPreference = 'Continue'
    $output = & gh @Arguments 2>&1
    $code = $LASTEXITCODE
    $out = @($output | Where-Object { $_ -isnot [Management.Automation.ErrorRecord] } |
        ForEach-Object { [string]$_ }) -join "`n"
    $err = @($output | Where-Object { $_ -is [Management.Automation.ErrorRecord] } |
        ForEach-Object { [string]$_ }) -join "`n"
    return [pscustomobject]@{ ExitCode = $code; Out = $out; Err = $err }
}

function Invoke-NativeE2eGh([string[]]$Arguments) {
    $result = Invoke-NativeE2eGhRaw $Arguments
    if ($result.ExitCode -ne 0) {
        throw "gh $($Arguments[0]) $($Arguments[1]) failed ($($result.ExitCode))."
    }
    return $result.Out
}

function Assert-NativeE2eGhLogin {
    if ((Invoke-NativeE2eGhRaw @('auth', 'status')).ExitCode -ne 0) {
        throw 'Sign in with your own GitHub CLI login first: gh auth login'
    }
}

function Get-NativeE2eNetworkPrefix([string]$Address, [int]$PrefixLength) {
    $bytes = ([Net.IPAddress]::Parse($Address)).GetAddressBytes()
    for ($i = 0; $i -lt 4; $i++) {
        $keep = [Math]::Max(0, [Math]::Min(8, $PrefixLength - 8 * $i))
        $mask = [byte]((0xFF -shl (8 - $keep)) -band 0xFF)
        $bytes[$i] = $bytes[$i] -band $mask
    }
    return ([Net.IPAddress]::new($bytes)).ToString()
}

function Test-NativeE2ePrefixOverlap([string]$First, [string]$Second) {
    # Two IPv4 prefixes overlap when both fall into the network of the shorter one.
    $a, $aLength = $First.Split('/')
    $b, $bLength = $Second.Split('/')
    $parsed = $null
    if (-not [Net.IPAddress]::TryParse($a, [ref]$parsed) -or
        -not [Net.IPAddress]::TryParse($b, [ref]$parsed)) { return $true }
    $shorter = [Math]::Min([int]$aLength, [int]$bLength)
    return (Get-NativeE2eNetworkPrefix $a $shorter) -eq (Get-NativeE2eNetworkPrefix $b $shorter)
}

function Assert-NativeE2eNoNat([string]$Prefix) {
    foreach ($nat in @(Get-NetNat -ErrorAction SilentlyContinue)) {
        foreach ($natPrefix in @($nat.InternalIPInterfaceAddressPrefix)) {
            if (Test-NativeE2ePrefixOverlap ([string]$natPrefix) $Prefix) {
                throw "NetNat '$($nat.Name)' ($natPrefix) covers $Prefix; the VM network must not be routed."
            }
        }
    }
}

function Test-NativeE2eUnscoped([string]$Value) {
    return @('', 'ANY', '*', '0.0.0.0/0', '::/0') -contains $Value.Trim()
}

function Assert-NativeE2eNetwork($State) {
    # Fail closed before the VM starts: internal switch, no NAT, ACLs present.
    $switch = Get-VMSwitch -Name $State.switch_name -ErrorAction Stop
    if ($switch.SwitchType -ne 'Internal') { throw "Switch $($State.switch_name) is not internal." }
    $prefix = '{0}/{1}' -f $State.network_prefix, $State.prefix_length
    Assert-NativeE2eNoNat $prefix
    $adapters = @(Get-VMNetworkAdapter -VMName $State.vm_name)
    if ($adapters.Count -ne 1 -or $adapters[0].SwitchName -ne $State.switch_name) {
        throw 'The VM must have exactly one network adapter, on the internal switch.'
    }
    $acls = @(Get-VMNetworkAdapterExtendedAcl -VMName $State.vm_name)
    # Each deny rule must cover every address, port and protocol.
    $unscoped = {
        (Test-NativeE2eUnscoped ([string]$_.LocalIPAddress)) -and
        (Test-NativeE2eUnscoped ([string]$_.RemoteIPAddress)) -and
        (Test-NativeE2eUnscoped ([string]$_.LocalPort)) -and
        (Test-NativeE2eUnscoped ([string]$_.RemotePort)) -and
        (Test-NativeE2eUnscoped ([string]$_.Protocol))
    }
    $deny = @($acls | Where-Object { $_.Action -eq 'Deny' })
    $denyOut = @($deny | Where-Object { $_.Direction -eq 'Outbound' } | Where-Object $unscoped)
    $denyIn = @($deny | Where-Object { $_.Direction -eq 'Inbound' } | Where-Object $unscoped)
    $allow = @($acls | Where-Object { $_.Action -eq 'Allow' })
    $hostTargets = @($State.host_address, "$($State.host_address)/32")
    $proxyOnly = $allow.Count -eq 1 -and $allow[0].Direction -eq 'Outbound' -and
        $hostTargets -contains [string]$allow[0].RemoteIPAddress -and
        [string]$allow[0].RemotePort -eq [string]$State.proxy_port -and
        @('6', 'TCP') -contains [string]$allow[0].Protocol
    if ($deny.Count -ne 2 -or $denyOut.Count -ne 1 -or $denyIn.Count -ne 1 -or -not $proxyOnly) {
        throw 'The VM adapter ACLs differ from the image recipe; rebuild the image.'
    }
}

function Set-NativeE2eAdapterAcls([string]$VmName, [string]$HostAddress, [int]$ProxyPort) {
    Get-VMNetworkAdapterExtendedAcl -VMName $VmName | Remove-VMNetworkAdapterExtendedAcl
    Add-VMNetworkAdapterExtendedAcl -VMName $VmName -Action Deny -Direction Outbound -Weight 1
    Add-VMNetworkAdapterExtendedAcl -VMName $VmName -Action Deny -Direction Inbound -Weight 1
    Add-VMNetworkAdapterExtendedAcl -VMName $VmName -Action Allow -Direction Outbound `
        -RemoteIPAddress $HostAddress -RemotePort ([string]$ProxyPort) -Protocol 'TCP' `
        -Weight 100 -Stateful $true
}
