"""Static checks of the native-e2e image runtime inputs (CAP-0174 WI-04).

The image build and guest provisioning act on Hyper-V and a VM, so they never run here:
these checks pin the Visual C++ runtime the guest needs and the failure message of the
test-phrase step.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "tools" / "native-e2e" / "host"
GUEST = ROOT / "tools" / "native-e2e" / "guest"


def code(path: Path) -> str:
    """PowerShell source without comment-help blocks and line comments."""
    text = re.sub(r"<#.*?#>", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
    lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    return "\n".join(line.split(" #", 1)[0] for line in lines)


def test_the_guest_installs_the_signed_vc_runtime_before_python() -> None:
    # The second build failed in step test-phrase: onnxruntime (Piper) imports MSVCP140.dll,
    # which a clean Windows has not got.
    host = code(HOST / "New-NativeE2eImage.ps1")
    fetch = host[host.index("function Get-VcRedist") :]
    fetch = fetch[: fetch.index("\n}\n")]
    assert "$VcRedistUrl = 'https://aka.ms/vs/17/release/vc_redist.x64.exe'" in host
    assert (
        "if ($signature.Status -ne 'Valid' -or "
        "$signature.SignerCertificate.Subject -notlike 'CN=Microsoft Corporation,*') {"
    ) in fetch
    assert "sha256 = Get-NativeE2eSha256 $file" in fetch
    assert "$vcRedist = Get-VcRedist $payload" in host and "vc_redist        = $vcRedist" in host
    assert "vc_redist_sha256       = $vcRedist.sha256" in host
    assert "vc_redist_version      = $vcRedist.version" in host
    guest = code(GUEST / "provision.ps1")
    step = guest[guest.index("Invoke-Step 'vc-redist'") : guest.index("Invoke-Step 'python'")]
    assert guest.index("Invoke-Step 'vc-redist'") < guest.index("Invoke-Step 'test-phrase'")
    assert (
        "$redist = Join-Path $Setup $inputs.vc_redist.file\n        Assert-Signed $redist" in step
    )
    assert "@('/install', '/quiet', '/norestart')" in step and "-Wait -PassThru" in step
    assert "if (@(0, 1638, 3010) -notcontains $process.ExitCode)" in step
    assert "$inputs.vc_redist.file" in guest[guest.index("Invoke-Step 'cleanup'") :]


def test_a_test_phrase_failure_names_its_stderr() -> None:
    source = code(GUEST / "provision.ps1")
    step = source[source.index("Invoke-Step 'test-phrase'") : source.index("Invoke-Step 'runner'")]
    assert "@(Invoke-NativeCaptured 'make_test_phrase.py' $venvPython @('-I'," in step
    assert "Where-Object { $_ -like '{*' } | Select-Object -Last 1" in step
    helper = source[source.index("function Invoke-NativeCaptured") :]
    helper = helper[: helper.index("\n}\n")]
    # Windows PowerShell 5.1 turns redirected native stderr into a terminating error under Stop.
    run = helper.index("& $FilePath @Arguments 2>&1")
    assert helper.index("$ErrorActionPreference = 'Continue'") < run
    assert run < helper.index("$output | Out-Host") < helper.index("if ($LASTEXITCODE -ne 0) {")
    failed = (
        'throw ("$Name exited with code ${LASTEXITCODE}: " + (($output | Select-Object -Last 4)'
    )
    assert helper.index("if ($LASTEXITCODE -ne 0) {") < helper.index(failed)
    # Every other native step (pip install, venv, icacls, ...) goes through the same capture.
    native = source[source.index("function Invoke-Native(") :]
    native = native[: native.index("\n}\n")]
    assert "Invoke-NativeCaptured $FilePath $FilePath $Arguments | Out-Null" in native
    assert "& $FilePath" not in native
    assert helper.endswith("\n    return $output")  # the test phrase reads the JSON line from it
