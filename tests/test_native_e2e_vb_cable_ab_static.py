"""The optional VB-Cable A+B image input and the job wait (automated-po-rows WI-09).

The image and run scripts act on Hyper-V and a VM, so they never run here: these checks pin
that ``-VbCableAbPackage`` is optional, that the guest installs it only when it was given and
waits for the endpoint names the Call Bridge rows read, and that the host waits longer for
the job than the workflow timeout.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from native_e2e.context import CABLE_AB_NAMES

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "tools" / "native-e2e" / "host"
GUEST = ROOT / "tools" / "native-e2e" / "guest"


def code(path: Path) -> str:
    """PowerShell source without comment-help blocks and line comments."""
    text = re.sub(r"<#.*?#>", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
    lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    return "\n".join(line.split(" #", 1)[0] for line in lines)


IMAGE = code(HOST / "New-NativeE2eImage.ps1")
PROVISION = code(GUEST / "provision.ps1")


def test_the_vb_cable_ab_package_is_an_optional_parameter() -> None:
    params = IMAGE[IMAGE.index("param(") : IMAGE.index("Set-StrictMode")]
    assert "[Parameter(Mandatory)][string]$VbCablePackage," in params
    assert "    [string]$VbCableAbPackage = ''," in params  # no Mandatory attribute
    assert "@($IsoPath, $VbCablePackage, $VbCableAbPackage) -ne ''" in IMAGE
    # Without the package build-inputs.json records null and the guest step does not run.
    assert "$vbCableAb = $null\nif ($VbCableAbPackage) {" in IMAGE
    assert re.search(r"^\s+vb_cable_ab\s+= \$vbCableAb$", IMAGE, re.MULTILINE)
    guarded = "if ($null -ne $inputs.vb_cable_ab) {\n        Invoke-Step 'vb-cable-ab' {"
    assert guarded in PROVISION


def test_the_guest_installs_a_plus_b_like_vb_cable_and_waits_for_its_endpoints() -> None:
    step = PROVISION[PROVISION.index("Invoke-Step 'vb-cable-ab'") :]
    step = step[: step.index("Invoke-Step 'test-phrase'")]
    assert PROVISION.index("Invoke-Step 'vb-cable'") < PROVISION.index("Invoke-Step 'vb-cable-ab'")
    assert "Assert-Signed $setupExe.FullName" in step
    assert "-ArgumentList @('-i', '-h') -Wait" in step
    assert "Get-ActiveEndpointName 'Render'" in step and "Get-ActiveEndpointName 'Capture'" in step
    names = {f"CABLE-{cable} {end}" for cable in "AB" for end in ("Input", "Output")}
    assert set(CABLE_AB_NAMES) == names
    assert '"CABLE-$cable Input"' in step and '"CABLE-$cable Output"' in step


def test_activation_moved_to_a_dot_sourced_guest_script_the_host_copies() -> None:
    assert ". (Join-Path $PSScriptRoot 'activation.ps1')" in PROVISION
    assert "function Invoke-GuestActivation" in code(GUEST / "activation.ps1")
    assert "'provision.ps1', 'activation.ps1', 'admin-helper.ps1', 'runner-logon.ps1'" in IMAGE


def test_every_guest_function_is_defined_once_across_provision_and_activation() -> None:
    def defined(text: str) -> list[str]:
        return re.findall(r"(?m)^function ([A-Za-z-]+)", text)

    both = defined(PROVISION) + defined(code(GUEST / "activation.ps1"))
    assert len(both) == len(set(both))  # a stub in provision.ps1 would shadow activation.ps1
    needed = r"\b(Set-ExclusiveAcl|Get-WindowsLicence|Invoke-GuestActivation)\b"
    called = set(re.findall(needed, PROVISION))
    assert called <= set(both)


def test_the_host_waits_longer_for_the_job_than_the_workflow_timeout() -> None:
    run = code(HOST / "Invoke-NativeE2eRun.ps1")
    wait = int(re.search(r"\[int\]\$JobTimeoutMinutes = (\d+)", run).group(1))
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "native-e2e.yml").read_text("utf-8")
    )
    jobs = [job.get("timeout-minutes", 0) for job in workflow["jobs"].values()]
    assert wait == 250 and wait > max(jobs)
