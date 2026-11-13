#Requires -Version 5.1
# Disk, network and VM helpers of New-NativeE2eImage.ps1 (CAP-0174). Dot-sourced; it changes
# nothing on its own. Every function acts only on the VM, VHDX, switch and firewall rule
# that the image script names.

Set-StrictMode -Version 3.0

$script:GptBasicData = '{ebd0a0a2-b9e5-4433-87c0-68b6b72699c7}'
$script:GptSystem = '{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}'
$script:GptReserved = '{e3c9e316-0b5c-4db8-817d-f92df00215ae}'
$script:ProxyRuleName = 'lianiq-native-e2e-proxy'

function Set-NativeE2eSwitch([string]$SwitchName, [string]$HostAddress, [int]$PrefixLength,
        [string]$GuestAddress, [int]$ProxyPort) {
    $switch = Get-VMSwitch -Name $SwitchName -ErrorAction SilentlyContinue
    if ($null -eq $switch) {
        Write-NativeE2eStep "Creating internal switch $SwitchName (no NAT)"
        New-VMSwitch -Name $SwitchName -SwitchType Internal | Out-Null
    } elseif ($switch.SwitchType -ne 'Internal') {
        throw "Switch $SwitchName exists and is not internal."
    }
    $prefix = '{0}/{1}' -f (Get-NativeE2eNetworkPrefix $HostAddress $PrefixLength), $PrefixLength
    Assert-NativeE2eNoNat $prefix
    $alias = "vEthernet ($SwitchName)"
    $current = @(Get-NetIPAddress -InterfaceAlias $alias -AddressFamily IPv4 -ErrorAction SilentlyContinue)
    if (-not ($current | Where-Object { $_.IPAddress -eq $HostAddress -and $_.PrefixLength -eq $PrefixLength })) {
        $current | Remove-NetIPAddress -Confirm:$false
        New-NetIPAddress -InterfaceAlias $alias -IPAddress $HostAddress -PrefixLength $PrefixLength | Out-Null
    }
    # The guest may reach only the proxy port on the host's switch address.
    Remove-NetFirewallRule -Name $script:ProxyRuleName -ErrorAction SilentlyContinue
    New-NetFirewallRule -Name $script:ProxyRuleName -DisplayName 'lianiq native-e2e egress proxy' `
        -Direction Inbound -Action Allow -Protocol TCP -LocalAddress $HostAddress `
        -LocalPort $ProxyPort -RemoteAddress $GuestAddress -Profile Any | Out-Null
    return $prefix
}

function Select-NativeE2eEdition([string]$ImageFile, [int]$ImageIndex) {
    $images = @(Get-WindowsImage -ImagePath $ImageFile)
    if ($ImageIndex -gt 0) {
        $chosen = @($images | Where-Object { $_.ImageIndex -eq $ImageIndex })
    } else {
        $chosen = @($images | Where-Object { $_.ImageName -like '*Enterprise*' -and $_.ImageName -notlike '* N *' })
    }
    if ($chosen.Count -ne 1) {
        $names = ($images | ForEach-Object { '{0}: {1}' -f $_.ImageIndex, $_.ImageName }) -join '; '
        throw "Choose the Enterprise evaluation edition with -ImageIndex ($names)."
    }
    return Get-WindowsImage -ImagePath $ImageFile -Index $chosen[0].ImageIndex
}

function New-NativeE2eSystemDisk([string]$VhdPath, [int]$SizeGB, [string]$ImageFile, $Edition,
        [string]$Unattend, [string]$Payload) {
    New-VHD -Path $VhdPath -SizeBytes ([int64]$SizeGB * 1GB) -Dynamic | Out-Null
    $disk = Mount-VHD -Path $VhdPath -Passthru | Get-Disk
    if ($disk.BusType -ne 'File Backed Virtual' -or $disk.PartitionStyle -ne 'RAW') {
        Dismount-VHD -Path $VhdPath
        throw 'The new VHDX did not mount as an empty virtual disk.'
    }
    try {
        Initialize-Disk -Number $disk.Number -PartitionStyle GPT
        $system = New-Partition -DiskNumber $disk.Number -Size 260MB -GptType $script:GptBasicData
        Format-Volume -Partition $system -FileSystem FAT32 -NewFileSystemLabel 'System' -Force -Confirm:$false | Out-Null
        $system | Set-Partition -GptType $script:GptSystem
        $system | Add-PartitionAccessPath -AssignDriveLetter
        if (-not (Get-Partition -DiskNumber $disk.Number | Where-Object { $_.GptType -eq $script:GptReserved })) {
            New-Partition -DiskNumber $disk.Number -Size 16MB -GptType $script:GptReserved | Out-Null
        }
        $windows = New-Partition -DiskNumber $disk.Number -UseMaximumSize -GptType $script:GptBasicData
        Format-Volume -Partition $windows -FileSystem NTFS -NewFileSystemLabel 'Windows' -Force -Confirm:$false | Out-Null
        $windows | Add-PartitionAccessPath -AssignDriveLetter
        $s = (Get-Partition -DiskNumber $disk.Number -PartitionNumber $system.PartitionNumber).DriveLetter
        $w = (Get-Partition -DiskNumber $disk.Number -PartitionNumber $windows.PartitionNumber).DriveLetter

        Write-NativeE2eStep "Applying $($Edition.ImageName) offline (several minutes)"
        Expand-WindowsImage -ImagePath $ImageFile -Index $Edition.ImageIndex -ApplyPath "${w}:\" | Out-Null
        & bcdboot.exe "${w}:\Windows" /s "${s}:" /f UEFI | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "bcdboot failed ($LASTEXITCODE)." }
        $panther = "${w}:\Windows\Panther"
        New-Item -ItemType Directory -Path $panther -Force | Out-Null
        [IO.File]::WriteAllText((Join-Path $panther 'unattend.xml'), $Unattend, (New-Object Text.UTF8Encoding $false))
        $setup = "${w}:\ProgramData\lianiq-e2e\setup"
        New-Item -ItemType Directory -Path $setup -Force | Out-Null
        Write-NativeE2eStep 'Copying the offline inputs into the image'
        Copy-Item -Path (Join-Path $Payload '*') -Destination $setup -Recurse -Force
        $system | Remove-PartitionAccessPath -AccessPath "${s}:\"
    } finally {
        Dismount-VHD -Path $VhdPath
    }
}

function Read-NativeE2eProvisionResult([string]$VhdPath, [string]$LogDir) {
    $disk = Mount-VHD -Path $VhdPath -ReadOnly -Passthru | Get-Disk
    try {
        $windows = Get-Partition -DiskNumber $disk.Number | Where-Object { $_.GptType -eq $script:GptBasicData }
        if (-not $windows.DriveLetter) { $windows | Add-PartitionAccessPath -AssignDriveLetter }
        $w = (Get-Partition -DiskNumber $disk.Number -PartitionNumber $windows.PartitionNumber).DriveLetter
        $root = "${w}:\ProgramData\lianiq-e2e"
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
        Copy-Item -LiteralPath "$root\setup\provision.log" -Destination $LogDir -Force -ErrorAction SilentlyContinue
        $resultPath = "$root\setup\provision-result.json"
        if (-not (Test-Path -LiteralPath $resultPath)) { throw "Provisioning left no result; see $LogDir." }
        $result = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
        if ($result.status -ne 'ok') {
            throw "Provisioning failed in step '$($result.step)': $($result.message). Log: $LogDir"
        }
        return Get-Content -LiteralPath "$root\image.json" -Raw -Encoding UTF8
    } finally {
        Dismount-VHD -Path $VhdPath
    }
}

function New-NativeE2eVm([string]$VmName, [string]$VhdPath, [string]$VmRoot, [string]$SwitchName,
        [string]$HostAddress, [int]$ProxyPort) {
    New-VM -Name $VmName -Generation 2 -MemoryStartupBytes 8GB -VHDPath $VhdPath `
        -SwitchName $SwitchName -Path $VmRoot | Out-Null
    Set-VM -Name $VmName -ProcessorCount 4 -StaticMemory -AutomaticCheckpointsEnabled $false `
        -CheckpointType Standard -AutomaticStartAction Nothing -AutomaticStopAction ShutDown
    Set-VMFirmware -VMName $VmName -EnableSecureBoot On -SecureBootTemplate 'MicrosoftWindows' `
        -FirstBootDevice (Get-VMHardDiskDrive -VMName $VmName)
    Set-VMKeyProtector -VMName $VmName -NewLocalKeyProtector
    Enable-VMTPM -VMName $VmName
    Set-VMVideo -VMName $VmName -HorizontalResolution 1920 -VerticalResolution 1080 -ResolutionType Single
    Set-VMNetworkAdapter -VMName $VmName -MacAddressSpoofing Off -DhcpGuard On -RouterGuard On
    # Copy-VMFile needs the guest service interface (host to guest only).
    Get-NativeE2eIntegrationService $VmName $script:NativeE2eGuestServiceId | Enable-VMIntegrationService
    Set-NativeE2eAdapterAcls $VmName $HostAddress $ProxyPort
}
