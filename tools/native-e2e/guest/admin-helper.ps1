#Requires -Version 5.1
<#
.SYNOPSIS
    Allow-listed admin helper of the native-e2e guest (CAP-0174, contract section 4.4).

.DESCRIPTION
    Runs as the SYSTEM scheduled task 'lianiq-e2e-admin-helper' (started at boot). The
    non-admin test user 'e2e' writes one request file per call into
    C:\ProgramData\lianiq-e2e\admin\requests\<id>.json, written under another name and then
    renamed so that the helper never reads a partial file:

        {"id": "<id>", "verb": "<verb>", "args": ["<arg>", ...]}

    <id> is 8-64 characters of [A-Za-z0-9-] and equals the file name. The helper deletes
    the request and writes C:\ProgramData\lianiq-e2e\admin\results\<id>.json atomically:

        {"id": "<id>", "verb": "<verb or null>", "ok": true|false,
         "value": "<string or null>", "error": "<reason or null>"}

    Exactly three verbs are executed:
        firewall-block-app <path>    adds the outbound block rule 'lianiq-e2e-block-app'
        firewall-unblock-app         removes that rule
        wfp-count <path> <since>     counts WFP events 5156/5157 of <path> since <since>
                                     (ISO 8601) whose addresses are not both loopback
    <path> must equal the 'interpreter' recorded in image.json. Any other verb, argument
    count or path is rejected with ok=false and logged; the log never contains a rejected
    path or argument.
#>
[CmdletBinding()]
param(
    [string]$Root = 'C:\ProgramData\lianiq-e2e',
    [int]$PollMilliseconds = 250,
    [switch]$Once
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

$AllowedVerbs = @('firewall-block-app', 'firewall-unblock-app', 'wfp-count')
$RuleName = 'lianiq-e2e-block-app'
$MaxRequestBytes = 4096
$IdPattern = '^[A-Za-z0-9-]{8,64}$'
$RequestDir = Join-Path $Root 'admin\requests'
$ResultDir = Join-Path $Root 'admin\results'
$LogPath = Join-Path $Root 'admin\helper.log'

function Write-HelperLog([string]$Message) {
    $line = '{0} {1}' -f [DateTime]::UtcNow.ToString('o'), $Message
    Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
}

function Get-PinnedInterpreter {
    $image = Get-Content -LiteralPath (Join-Path $Root 'image.json') -Raw -Encoding UTF8 |
        ConvertFrom-Json
    $path = [string]$image.interpreter
    if (-not [IO.Path]::IsPathRooted($path)) { throw 'image.json has no rooted interpreter path.' }
    return [IO.Path]::GetFullPath($path)
}

function Test-PinnedPath([string]$Candidate, [string]$Pinned) {
    if ([string]::IsNullOrWhiteSpace($Candidate)) { return $false }
    if ($Candidate.IndexOfAny([char[]]'*?"<>|') -ge 0) { return $false }
    if (-not [IO.Path]::IsPathRooted($Candidate)) { return $false }
    try { $full = [IO.Path]::GetFullPath($Candidate) } catch { return $false }
    return [string]::Equals($full, $Pinned, [StringComparison]::OrdinalIgnoreCase) -and
        [string]::Equals($Candidate, $full, [StringComparison]::OrdinalIgnoreCase)
}

function Test-Loopback([string]$Address) {
    $parsed = $null
    if (-not [Net.IPAddress]::TryParse($Address, [ref]$parsed)) { return $false }
    return [Net.IPAddress]::IsLoopback($parsed)
}

function Get-WfpCount([string]$Pinned, [DateTime]$Since) {
    # WFP events name the program by device path (\device\harddiskvolumeN\...): compare the
    # path below the volume root.
    $tail = $Pinned.Substring([IO.Path]::GetPathRoot($Pinned).Length - 1)
    $filter = @{ LogName = 'Security'; Id = 5156, 5157; StartTime = $Since }
    try {
        $events = @(Get-WinEvent -FilterHashtable $filter -ErrorAction Stop)
    } catch {
        if ($_.FullyQualifiedErrorId -notlike 'NoMatchingEventsFound*') { throw }
        $events = @()
    }
    $count = 0
    foreach ($record in $events) {
        $data = @{}
        foreach ($item in ([xml]$record.ToXml()).Event.EventData.Data) {
            $data[[string]$item.Name] = [string]$item.'#text'
        }
        $application = [string]$data['Application']
        if (-not $application.StartsWith('\device\', [StringComparison]::OrdinalIgnoreCase)) {
            continue
        }
        if (-not $application.EndsWith($tail, [StringComparison]::OrdinalIgnoreCase)) { continue }
        $volume = $application.Substring(0, $application.Length - $tail.Length)
        if ($volume.Substring(8).Contains('\')) { continue }
        if ((Test-Loopback $data['SourceAddress']) -and (Test-Loopback $data['DestAddress'])) {
            continue
        }
        $count++
    }
    return $count
}

function New-VerbResult([bool]$Ok, $Value, $Reason) {
    return [pscustomobject]@{ Ok = $Ok; Value = $Value; Reason = $Reason }
}

function Invoke-AllowedVerb([string]$Verb, [string[]]$Arguments, [string]$Pinned) {
    switch -CaseSensitive ($Verb) {
        'firewall-block-app' {
            if ($Arguments.Count -ne 1) { return (New-VerbResult $false $null 'argument-count') }
            if (-not (Test-PinnedPath $Arguments[0] $Pinned)) {
                return (New-VerbResult $false $null 'path-not-allowed')
            }
            Remove-NetFirewallRule -Name $RuleName -ErrorAction SilentlyContinue
            New-NetFirewallRule -Name $RuleName -DisplayName $RuleName -Direction Outbound `
                -Action Block -Program $Pinned -Profile Any -Enabled True | Out-Null
            return (New-VerbResult $true $RuleName $null)
        }
        'firewall-unblock-app' {
            if ($Arguments.Count -ne 0) { return (New-VerbResult $false $null 'argument-count') }
            $rule = Get-NetFirewallRule -Name $RuleName -ErrorAction SilentlyContinue
            if ($null -eq $rule) { return (New-VerbResult $true 'absent' $null) }
            Remove-NetFirewallRule -Name $RuleName
            return (New-VerbResult $true 'removed' $null)
        }
        'wfp-count' {
            if ($Arguments.Count -ne 2) { return (New-VerbResult $false $null 'argument-count') }
            if (-not (Test-PinnedPath $Arguments[0] $Pinned)) {
                return (New-VerbResult $false $null 'path-not-allowed')
            }
            $since = [DateTime]::MinValue
            $styles = [Globalization.DateTimeStyles]::AdjustToUniversal -bor
                [Globalization.DateTimeStyles]::AssumeUniversal
            if (-not [DateTime]::TryParse($Arguments[1],
                    [Globalization.CultureInfo]::InvariantCulture, $styles, [ref]$since)) {
                return (New-VerbResult $false $null 'since-not-a-timestamp')
            }
            $count = [string](Get-WfpCount $Pinned $since.ToLocalTime())
            return (New-VerbResult $true $count $null)
        }
        default { return (New-VerbResult $false $null 'verb-not-allowed') }
    }
}

function Get-RequestField($Request, [string]$Name) {
    if ($Request -isnot [pscustomobject]) { return $null }
    $property = $Request.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Write-Result([string]$Id, $Verb, [bool]$Ok, $Value, $Reason) {
    $payload = [ordered]@{ id = $Id; verb = $Verb; ok = $Ok; value = $Value; error = $Reason }
    $temporary = Join-Path $ResultDir ('.{0}.tmp' -f $Id)
    $final = Join-Path $ResultDir ('{0}.json' -f $Id)
    [IO.File]::WriteAllText($temporary, ($payload | ConvertTo-Json -Compress),
        (New-Object Text.UTF8Encoding $false))
    Move-Item -LiteralPath $temporary -Destination $final -Force
}

function Invoke-Request([IO.FileInfo]$File, [string]$Pinned) {
    $id = [IO.Path]::GetFileNameWithoutExtension($File.Name)
    $isReparse = ($File.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
    $size = $File.Length
    $raw = $null
    if (-not $isReparse -and $size -le $MaxRequestBytes) {
        $raw = [IO.File]::ReadAllText($File.FullName)
    }
    Remove-Item -LiteralPath $File.FullName -Force
    if ($id -notmatch $IdPattern) { Write-HelperLog 'rejected reason=bad-id'; return }
    if ($null -eq $raw) {
        Write-HelperLog "rejected id=$id reason=request-not-a-small-file"
        Write-Result $id $null $false $null 'request-not-a-small-file'
        return
    }
    try { $request = $raw | ConvertFrom-Json } catch { $request = $null }
    $verb = Get-RequestField $request 'verb'
    $arguments = @()
    $valid = (Get-RequestField $request 'id') -is [string] -and
        (Get-RequestField $request 'id') -ceq $id -and $verb -is [string]
    if ($valid) {
        foreach ($item in @(Get-RequestField $request 'args')) {
            if ($null -eq $item) { continue }
            if ($item -isnot [string]) { $valid = $false }
            $arguments += [string]$item
        }
    }
    if (-not $valid) {
        Write-HelperLog "rejected id=$id reason=malformed-request"
        Write-Result $id $null $false $null 'malformed-request'
        return
    }
    if ($AllowedVerbs -cnotcontains $verb) {
        Write-HelperLog "rejected id=$id reason=verb-not-allowed"
        Write-Result $id $null $false $null 'verb-not-allowed'
        return
    }
    try {
        $result = Invoke-AllowedVerb $verb $arguments $Pinned
    } catch {
        $result = New-VerbResult $false $null 'verb-failed'
    }
    $state = if ($result.Ok) { 'done' } else { "rejected reason=$($result.Reason)" }
    Write-HelperLog "id=$id verb=$verb $state"
    Write-Result $id $verb $result.Ok $result.Value $result.Reason
}

function Restore-RequestDir {
    # Recreate a missing request folder with the provisioning ACL: inherited read for
    # Users plus Modify for the test user only.
    $user = [string](Get-Content -LiteralPath (Join-Path $Root 'image.json') -Raw -Encoding UTF8 |
        ConvertFrom-Json).test_user
    if ($user -notmatch '^[A-Za-z0-9_-]{1,20}$') { throw 'image.json has no valid test_user.' }
    New-Item -ItemType Directory -Path $RequestDir -Force | Out-Null
    & icacls.exe $RequestDir /grant "${user}:(OI)(CI)M" /q | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'icacls failed on the request folder.' }
    Write-HelperLog 'recreated the request folder'
}

function Remove-BadRequest([IO.FileInfo]$File) {
    # A request that cannot be read is deleted; one that cannot be deleted either is
    # skipped and logged once, so the poll loop never spins on it.
    Remove-Item -LiteralPath $File.FullName -Force -ErrorAction SilentlyContinue
    if (-not (Test-Path -LiteralPath $File.FullName)) {
        Write-HelperLog 'rejected reason=unreadable-request-deleted'
        return
    }
    $key = '{0}|{1}' -f $File.FullName, $File.LastWriteTimeUtc.Ticks
    if ($script:Skipped.Add($key)) { Write-HelperLog 'skipped reason=undeletable-request' }
}

$pinned = Get-PinnedInterpreter
$script:Skipped = New-Object 'System.Collections.Generic.HashSet[string]'
Write-HelperLog "started verbs=$($AllowedVerbs -join ',')"
do {
    try {
        if (-not (Test-Path -LiteralPath $RequestDir -PathType Container)) { Restore-RequestDir }
        $pending = @(Get-ChildItem -LiteralPath $RequestDir -File -Filter '*.json' |
            Where-Object { -not $script:Skipped.Contains(('{0}|{1}' -f $_.FullName, $_.LastWriteTimeUtc.Ticks)) } |
            Sort-Object LastWriteTimeUtc)
    } catch {
        Write-HelperLog 'request-folder-error'
        $pending = @()
        if (-not $Once) { Start-Sleep -Seconds 5 }
    }
    foreach ($file in $pending) {
        try { Invoke-Request $file $pinned } catch { Remove-BadRequest $file }
    }
    if (-not $Once) { Start-Sleep -Milliseconds $PollMilliseconds }
} while (-not $Once)
