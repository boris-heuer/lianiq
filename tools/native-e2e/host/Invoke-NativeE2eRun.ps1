#Requires -Version 5.1
<#
.SYNOPSIS
    Runs one native-e2e job on the VM (CAP-0174, spec section 2.2.1, contract section 4).

.DESCRIPTION
    PO step, run as administrator after a native-e2e workflow run was dispatched. The script
    checks the network isolation, reverts the VM to checkpoint 'clean', starts the egress
    proxy and the VM, waits for the Hyper-V heartbeat, requests a one-job JIT runner
    configuration with the PO's own GitHub CLI login and copies it into the guest with
    Copy-VMFile. The PO then approves the run in the GitHub environment 'native-e2e'.
    After the job the runner is gone; the script shuts the VM down, reverts it to 'clean'
    and prints the run URL and the SHA-256 of native-evidence.json.

    It never retries. On an infrastructure fault (runner not online within
    -RunnerOnlineMinutes, VM boot failure, job lost) it reports the fault, cleans up and
    exits non-zero; the PO may start it once more.

.PARAMETER NoRevert
    Diagnostic only (AC-16, E-09): skips the revert to 'clean' at the start and at the end
    of this invocation, so the disk keeps the previous run's state.
#>
[CmdletBinding()]
param(
    [switch]$NoRevert,
    [string]$StateRoot = (Join-Path $env:ProgramData 'lianiq-native-e2e'),
    [int]$BootMinutes = 10,
    [int]$RunnerOnlineMinutes = 10,
    [int]$JobTimeoutMinutes = 180
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'NativeE2e.Host.ps1')

$Repo = $script:NativeE2eRepository
$JitDestination = Join-Path $script:NativeE2eGuestRoot 'jit\jitconfig'

function Get-RunnerState([string]$RunnerId) {
    # Kind 'runner' (with Runner), 'gone' (HTTP 404: GitHub removed the JIT runner) or
    # 'error' (any other failure; never read as a finished job).
    $result = Invoke-NativeE2eGhRaw @('api', "repos/$Repo/actions/runners/$RunnerId")
    $code = $result.ExitCode
    if ($code -eq 0) {
        try {
            return [pscustomobject]@{ Kind = 'runner'; Runner = ($result.Out | ConvertFrom-Json); Message = $null }
        } catch {
            return [pscustomobject]@{ Kind = 'error'; Runner = $null; Message = 'unreadable runner state' }
        }
    }
    if ("$($result.Err)`n$($result.Out)" -match 'HTTP 404') {
        return [pscustomobject]@{ Kind = 'gone'; Runner = $null; Message = $null }
    }
    return [pscustomobject]@{ Kind = 'error'; Runner = $null; Message = "gh api exited $code" }
}

function Test-JobFinished($Probe, [bool]$SawBusy) {
    # Only a 404 after the runner was busy, or not busy after busy, ends the job.
    if (-not $SawBusy) { return $false }
    if ($Probe.Kind -eq 'gone') { return $true }
    return $Probe.Kind -eq 'runner' -and -not $Probe.Runner.busy
}

function Remove-Runner([string]$RunnerId) {
    $result = Invoke-NativeE2eGhRaw @('api', '--method', 'DELETE', "repos/$Repo/actions/runners/$RunnerId")
    if ($result.ExitCode -ne 0 -and "$($result.Err)" -notmatch 'HTTP 404') {
        throw "Removing JIT runner $RunnerId failed ($($result.ExitCode)); remove it in the repository settings."
    }
}

function Start-EgressProxy($State, [string]$LogFile) {
    $proxyScript = Join-Path $PSScriptRoot 'egress-proxy.py'
    $arguments = @('-I', "`"$proxyScript`"", '--listen', $State.host_address, '--port', $State.proxy_port,
        '--allowlist', "`"$(Join-Path $PSScriptRoot 'egress-allowlist.txt')`"", '--log', "`"$LogFile`"")
    $process = Start-Process -FilePath $State.host_python -ArgumentList $arguments -PassThru -WindowStyle Hidden
    Wait-NativeE2eCondition {
        if ($process.HasExited) { throw 'The egress proxy exited; see its log.' }
        @(Get-NetTCPConnection -LocalAddress $State.host_address -LocalPort $State.proxy_port `
                -State Listen -ErrorAction SilentlyContinue).Count -gt 0
    } 30 1 'egress proxy listening'
    return $process
}

function Stop-Guest([string]$VmName) {
    if ((Get-VM -Name $VmName).State -eq 'Off') { return }
    try {
        Stop-VM -Name $VmName -Force
    } catch {
        Write-Warning "Guest shutdown failed ($($_.Exception.Message)); turning the VM off."
    }
    if ((Get-VM -Name $VmName).State -ne 'Off') { Stop-VM -Name $VmName -TurnOff -Force }
}

function Invoke-Cleanup([string]$What, [scriptblock]$Body) {
    try {
        & $Body | Out-Null
        return $true
    } catch {
        Write-NativeE2eStep "CLEANUP FAILED ($What): $($_.Exception.Message)"
        return $false
    }
}

function Restore-Clean([string]$VmName) {
    Restore-VMSnapshot -VMName $VmName -Name $script:NativeE2eCheckpoint -Confirm:$false
}

function Copy-JitConfig([string]$VmName, [string]$EncodedConfig) {
    $folder = Join-Path $env:TEMP ('lianiq-e2e-jit-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $folder | Out-Null
    & icacls.exe $folder /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' /q | Out-Null
    $file = Join-Path $folder 'jitconfig'
    try {
        [IO.File]::WriteAllText($file, $EncodedConfig, (New-Object Text.UTF8Encoding $false))
        Wait-NativeE2eCondition {
            try {
                Copy-VMFile -Name $VmName -SourcePath $file -DestinationPath $JitDestination `
                    -FileSource Host -CreateFullPath -Force
                $true
            } catch { $false }
        } 300 5 'Copy-VMFile of the JIT configuration'
    } finally {
        Remove-Item -LiteralPath $folder -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Find-Run([string]$RunnerName) {
    $runs = Invoke-NativeE2eGh @('api', "repos/$Repo/actions/workflows/native-e2e.yml/runs?per_page=20") |
        ConvertFrom-Json
    foreach ($run in $runs.workflow_runs) {
        $jobs = Invoke-NativeE2eGh @('api', "repos/$Repo/actions/runs/$($run.id)/jobs") | ConvertFrom-Json
        if (@($jobs.jobs | Where-Object { $_.runner_name -eq $RunnerName }).Count -gt 0) { return $run }
    }
    return $null
}

function Show-Evidence($Run) {
    if ($null -eq $Run) { Write-NativeE2eStep 'No workflow run used this runner.'; return }
    Write-NativeE2eStep "Run: $($Run.html_url) ($($Run.conclusion))"
    $target = Join-Path $StateRoot "runs\$($Run.id)"
    $download = Invoke-NativeE2eGhRaw @('run', 'download', [string]$Run.id, '--repo', $Repo,
        '--pattern', 'native-e2e-*', '--dir', $target)
    if ($download.ExitCode -ne 0) {
        Write-NativeE2eStep 'No artifact was uploaded (failed job or redaction gate).'
        return
    }
    $receipt = Get-ChildItem -LiteralPath $target -Recurse -Filter 'native-evidence.json' -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $receipt) {
        Write-NativeE2eStep 'No artifact was uploaded (failed job or redaction gate).'
        return
    }
    Write-NativeE2eStep "native-evidence.json SHA-256: $(Get-NativeE2eSha256 $receipt.FullName)"
    Write-NativeE2eStep "Artifact copy: $($receipt.DirectoryName)"
}

Assert-NativeE2eAdministrator
Assert-NativeE2eGhLogin
$state = Read-NativeE2eHostState $StateRoot
$vm = $state.vm_name
if (-not (Get-VMSnapshot -VMName $vm -Name $script:NativeE2eCheckpoint -ErrorAction SilentlyContinue)) {
    throw "Checkpoint '$($script:NativeE2eCheckpoint)' is missing; rebuild the image."
}
Assert-NativeE2eNetwork $state

$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddHHmmss')
$logDir = Join-Path $StateRoot 'logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$runnerName = "win11-native-e2e-$($state.image_id)-$stamp"
$proxy = $null
$runnerId = $null
$exitCode = 0
try {
    Stop-Guest $vm
    if ($NoRevert) {
        Write-NativeE2eStep 'DIAGNOSTIC -NoRevert: the VM is NOT reverted to clean (AC-16).'
    } else {
        Write-NativeE2eStep "Reverting $vm to '$($script:NativeE2eCheckpoint)'"
        Restore-Clean $vm
    }
    $proxy = Start-EgressProxy $state (Join-Path $logDir "egress-proxy-$stamp.log")
    Write-NativeE2eStep 'Starting the VM'
    Start-VM -Name $vm
    Wait-NativeE2eCondition { "$((Get-VM -Name $vm).Heartbeat)" -like 'Ok*' } ($BootMinutes * 60) 5 'VM heartbeat'

    Write-NativeE2eStep "Requesting a one-job JIT runner configuration ($runnerName)"
    $jitArgs = @('api', '--method', 'POST', "repos/$Repo/actions/runners/generate-jitconfig",
        '-f', "name=$runnerName", '-F', 'runner_group_id=1', '-f', 'work_folder=_work')
    foreach ($label in $script:NativeE2eRunnerLabels) { $jitArgs += @('-f', "labels[]=$label") }
    $jit = Invoke-NativeE2eGh $jitArgs | ConvertFrom-Json
    $runnerId = [string]$jit.runner.id
    Copy-JitConfig $vm ([string]$jit.encoded_jit_config)
    $jit = $null

    Write-NativeE2eStep "Waiting up to $RunnerOnlineMinutes min for the runner to come online"
    try {
        Wait-NativeE2eCondition {
            $probe = Get-RunnerState $runnerId
            if ($probe.Kind -eq 'error') { Write-Warning "Runner state unavailable: $($probe.Message)" }
            $probe.Kind -eq 'runner' -and $probe.Runner.status -eq 'online'
        } ($RunnerOnlineMinutes * 60) 10 'runner online'
    } catch {
        throw "Infrastructure fault: the runner did not come online within $RunnerOnlineMinutes minutes."
    }
    Write-NativeE2eStep 'Runner online. Approve the run in GitHub (environment native-e2e).'
    $script:sawBusy = $false
    try {
        Wait-NativeE2eCondition {
            $probe = Get-RunnerState $runnerId
            if ($probe.Kind -eq 'error') { Write-Warning "Runner state unavailable: $($probe.Message)" }
            if ($probe.Kind -eq 'runner' -and $probe.Runner.busy) { $script:sawBusy = $true }
            if ($probe.Kind -eq 'gone' -and -not $script:sawBusy) {
                # A job shorter than one poll (for example an early S-01 block) can finish
                # unseen: the runner counts as used when a workflow run names it.
                $used = $null
                try { $used = Find-Run $runnerName } catch { Write-Warning "Run lookup failed: $($_.Exception.Message)" }
                if ($null -eq $used) { throw 'Infrastructure fault: the runner disappeared before it took a job.' }
                $script:sawBusy = $true
            }
            if ((Get-VM -Name $vm).State -ne 'Running') { throw 'Infrastructure fault: the VM stopped during the job.' }
            Test-JobFinished $probe $script:sawBusy
        } ($JobTimeoutMinutes * 60) 15 'job completion'
    } catch {
        if ($_.Exception.Message -like 'Infrastructure fault:*') { throw }
        throw "Infrastructure fault: the job did not finish within $JobTimeoutMinutes minutes."
    }
    $runnerId = $null
    Show-Evidence (Find-Run $runnerName)
} catch {
    Write-NativeE2eStep "FAILED: $($_.Exception.Message)"
    $exitCode = 1
} finally {
    # Each cleanup step runs even when an earlier one throws; any failure makes the exit non-zero.
    $cleanOk = $true
    if ($null -ne $runnerId) {
        $cleanOk = (Invoke-Cleanup 'remove runner' { Remove-Runner $runnerId }) -and $cleanOk
    }
    Write-NativeE2eStep 'Shutting the VM down'
    $cleanOk = (Invoke-Cleanup 'stop VM' { Stop-Guest $vm }) -and $cleanOk
    if ($null -ne $proxy) {
        $cleanOk = (Invoke-Cleanup 'stop proxy' {
                if (-not $proxy.HasExited) { Stop-Process -Id $proxy.Id -Force }
            }) -and $cleanOk
    }
    if ($NoRevert) {
        Write-NativeE2eStep 'DIAGNOSTIC -NoRevert: the VM stays unreverted. Run without -NoRevert to restore it.'
    } elseif (Invoke-Cleanup 'revert' { Restore-Clean $vm }) {
        Write-NativeE2eStep "VM off and reverted to '$($script:NativeE2eCheckpoint)'."
    } else {
        $cleanOk = $false
    }
    if (-not $cleanOk) {
        Write-NativeE2eStep 'Finish the cleanup in Hyper-V Manager: turn the VM off and apply checkpoint clean.'
        if ($exitCode -eq 0) { $exitCode = 3 }
    }
}
exit $exitCode
