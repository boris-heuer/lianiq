#Requires -Version 5.1
<#
.SYNOPSIS
    Starts the one-job GitHub Actions runner in the signed-in 'e2e' session (CAP-0174).

.DESCRIPTION
    Runs as the logon task 'lianiq-e2e-runner-logon' of the non-admin user 'e2e' in its
    interactive session, so the job can drive the real window. It waits for the JIT runner
    configuration that Invoke-NativeE2eRun.ps1 copies in with Copy-VMFile, reads it, deletes
    the file and starts the runner once with it. The runner is not a service and holds no
    reusable credential; the JIT configuration is invalid after its one job. The
    configuration is never written to the log. MinGit's cmd folder is put on PATH for this
    process and the runner it starts only (S-01 and actions/checkout need git); the system
    and user PATH stay unchanged.
#>
[CmdletBinding()]
param(
    [string]$Root = 'C:\ProgramData\lianiq-e2e',
    [string]$RunnerDir = 'C:\actions-runner',
    [int]$WaitMinutes = 60
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

$JitPath = Join-Path $Root 'jit\jitconfig'
$LogPath = Join-Path $Root 'state\runner-logon.log'

function Write-LogonLog([string]$Message) {
    $line = '{0} {1}' -f [DateTime]::UtcNow.ToString('o'), $Message
    Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
}

function Read-JitConfig {
    # Copy-VMFile may still be writing: accept the file only when it decodes to JSON.
    if (-not (Test-Path -LiteralPath $JitPath -PathType Leaf)) { return $null }
    try {
        $text = ([IO.File]::ReadAllText($JitPath)).Trim()
        if ($text -notmatch '^[A-Za-z0-9+/]+={0,2}$') { return $null }
        $json = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($text))
        $null = $json | ConvertFrom-Json
        return $text
    } catch {
        return $null
    }
}

Write-LogonLog "logon user=$env:USERNAME waiting for the JIT configuration"
$deadline = [DateTime]::UtcNow.AddMinutes($WaitMinutes)
$config = $null
while ($null -eq $config) {
    if ([DateTime]::UtcNow -gt $deadline) {
        Write-LogonLog 'no JIT configuration arrived; the runner was not started'
        exit 2
    }
    Start-Sleep -Seconds 2
    $config = Read-JitConfig
}
Remove-Item -LiteralPath $JitPath -Force
Write-LogonLog 'JIT configuration received; starting the runner'

$MinGitCmd = Join-Path $Root 'mingit\cmd'
if (-not (Test-Path -LiteralPath (Join-Path $MinGitCmd 'git.exe') -PathType Leaf)) {
    Write-LogonLog "git.exe is missing in $MinGitCmd; the job reports git-not-available"
}
$env:PATH = "$MinGitCmd;$env:PATH"

$runner = Join-Path $RunnerDir 'run.cmd'
Push-Location -LiteralPath $RunnerDir
try {
    & $runner --jitconfig $config
    $code = $LASTEXITCODE
} finally {
    Pop-Location
    $config = $null
}
Write-LogonLog "runner exited code=$code"
exit $code
