#Requires -Version 5.1
<#
.SYNOPSIS
    Windows activation of the native-e2e guest at image build (CAP-0174, contract 7.4).

.DESCRIPTION
    Dot-sourced by provision.ps1 from the same setup folder. Get-WindowsLicence reads the
    installed Windows licence (status, channel and grace period only, never the key);
    Invoke-GuestActivation activates it online through the host's build-only proxy and
    returns the result and, for an evaluation, the expiry.
#>

# Windows in the Software Licensing Service.
$WindowsAppId = '55c92734-d682-4d71-983e-d6ec3f16059f'

function Get-WindowsLicence {
    # Status, channel and grace period only; no part of the product key is read or logged.
    $filter = "ApplicationID='$WindowsAppId' AND LicenseIsAddon=False AND PartialProductKey IS NOT NULL"
    # sppsvc stops when idle; a query during the stop fails: retry.
    for ($try = 1; ; $try++) {
        try { $products = @(Get-CimInstance -ClassName SoftwareLicensingProduct -Filter $filter); break }
        catch { if ($try -ge 6) { throw }; Write-Host "Licence query $try failed: $($_.Exception.Message)" }
        Start-Sleep -Seconds 10
    }
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
