"""Build-only Windows activation and the evaluation expiry guard (CAP-0174 WI-02, contract 7.4).

The scripts drive Hyper-V, so they never run here. Static checks pin the activation step
(build-only allow-list, WinHTTP proxy reset in a finally path, no key parameter) and the
run script's expiry refusal; the pure expiry and media helpers also run in PowerShell when
it is installed.
"""

from __future__ import annotations

import base64
import importlib.util
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "tools" / "native-e2e" / "host"
GUEST = ROOT / "tools" / "native-e2e" / "guest"
ACTIVATION = HOST / "activation-allowlist.txt"
SCRIPTS = sorted([*HOST.glob("*.ps1"), *GUEST.glob("*.ps1")])


def code(path: Path) -> str:
    """PowerShell source without comment-help blocks and line comments."""
    text = re.sub(r"<#.*?#>", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
    lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    return "\n".join(line.split(" #", 1)[0] for line in lines)


def load_proxy():
    spec = importlib.util.spec_from_file_location("native_e2e_proxy_act", HOST / "egress-proxy.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def powershell(script: str) -> list[str]:
    exe = shutil.which("pwsh") or shutil.which("powershell")
    if exe is None:
        pytest.skip("PowerShell is not installed")
    helpers = "; ".join(
        f". '{HOST / name}'" for name in ("NativeE2e.Host.ps1", "NativeE2e.Image.ps1")
    )
    body = f"$ErrorActionPreference = 'Stop'; {helpers}; {script}"
    encoded = base64.b64encode(body.encode("utf-16-le")).decode("ascii")
    completed = subprocess.run(
        [
            exe,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.split()


def test_the_activation_list_holds_exact_microsoft_hosts_only() -> None:
    text = ACTIVATION.read_text(encoding="utf-8")
    entries = load_proxy().parse_allowlist(text)  # the proxy loads the same format
    assert "*" not in "".join(entries)
    sls = [f"{name}.sls.microsoft.com" for name in ("activation", "validation")]
    sls += [host.replace(".sls", "-v2.sls") for host in sls]
    store = [
        f"{name}.{zone}microsoft.com"
        for name in ("licensing", "displaycatalog", "purchase")
        for zone in ("mp.", "md.mp.")
    ]
    expected = set(sls + store + ["go.microsoft.com", "login.live.com"])
    assert len(entries) == len(set(entries)) == 12
    assert set(entries) == expected  # exact hosts: no wildcard, no extra host
    assert "first build" in text and "native-e2e-setup.md" in text
    egress = load_proxy().parse_allowlist((HOST / "egress-allowlist.txt").read_text("utf-8"))
    assert set(entries).isdisjoint(egress)


def test_runs_only_ever_use_the_egress_list() -> None:
    for name in ("Invoke-NativeE2eRun.ps1", "NativeE2e.Host.ps1"):
        assert "activation-allowlist" not in (HOST / name).read_text(encoding="utf-8"), name
    run = code(HOST / "Invoke-NativeE2eRun.ps1")
    assert "(Join-Path $PSScriptRoot 'egress-allowlist.txt')" in run
    image = code(HOST / "New-NativeE2eImage.ps1")
    assert "(Join-Path $PSScriptRoot 'activation-allowlist.txt')" in image
    assert "egress-allowlist.txt" not in image


def test_the_licence_source_is_a_validated_switch_and_the_key_never_a_parameter() -> None:
    image = code(HOST / "New-NativeE2eImage.ps1")
    params = image[image.index("param(") : image.index("Set-StrictMode")]
    assert "[ValidateSet('evaluation', 'key')][string]$LicenceSource = 'evaluation'" in params
    names = re.findall(r"\$(\w+)", params)
    assert [name for name in names if "key" in name.lower()] == []
    for path in SCRIPTS:
        source = code(path)
        for forbidden in ("slmgr", "/ipk", "InstallProductKey", ".PartialProductKey", "Read-Host"):
            assert forbidden not in source, (path.name, forbidden)
    provision = code(GUEST / "provision.ps1")
    assert "Start-Process -FilePath 'slui.exe' -ArgumentList '3'" in provision
    assert re.search(r"licence_source\s+= \$LicenceSource$", image, re.MULTILINE)
    assert re.search(
        r"licence_source\s+= \[string\]\$inputs\.licence_source$", provision, re.MULTILINE
    )


def test_the_winhttp_proxy_is_reset_in_a_finally_path() -> None:
    provision = code(GUEST / "provision.ps1")
    step = provision[provision.index("Invoke-Step 'activation'") :]
    step = step[: step.index("Invoke-Step 'image-json'")]
    set_at = step.index("@('winhttp', 'set', 'proxy'")
    try_at = step.index("try {")
    finally_at = step.index("} finally {")
    reset_at = step.index("@('winhttp', 'reset', 'proxy')")
    assert try_at < set_at < finally_at < reset_at
    assert "Invoke-GuestActivation" in step[set_at:finally_at]
    netsh = provision[provision.index("function Invoke-Netsh") :]
    netsh = netsh[: netsh.index("\n}")]
    assert "$ErrorActionPreference = 'Continue'" in netsh and "& netsh.exe" in netsh
    assert provision.count("& netsh.exe") == 1


def test_the_build_proxy_runs_once_and_stops_before_the_checkpoint() -> None:
    image = code(HOST / "New-NativeE2eImage.ps1")
    start = image.index("$activationProxy = Start-NativeE2eEgressProxy")
    assert image.count("Start-NativeE2eEgressProxy") == 1
    stop = image.index("Stop-NativeE2eEgressProxy $activationProxy")
    assert image.index("New-NativeE2eVm $VmName") < start < image.index("Start-VM -Name $VmName")
    assert start < image.index("} finally {", start) < stop
    assert stop < image.index("Checkpoint-VM -Name $VmName")
    assert image.index("Assert-NativeE2eLicenceMedia $LicenceSource $edition") < image.index(
        "New-NativeE2eSystemDisk"
    )


def test_image_json_records_the_licence_and_the_expiry_for_evaluation_only() -> None:
    provision = code(GUEST / "provision.ps1")
    record = provision[provision.index("Invoke-Step 'image-json'") :]
    for field in ("licence_source", "activation", "windows_edition"):
        assert f"{field} " in record, field
    assert "if ($inputs.licence_source -eq 'evaluation')" in record
    assert "$image['licence_expires'] = $script:licence.Expires" in record


def test_the_run_refuses_an_expired_image_before_the_vm_starts() -> None:
    run = code(HOST / "Invoke-NativeE2eRun.ps1")
    check = run.index("Get-NativeE2eLicenceState (Read-NativeE2eImage $StateRoot)")
    for later in ("Stop-Guest $vm\n", "Restore-Clean $vm", "Start-VM -Name $vm"):
        assert check < run.index(later), later
    guard = run[check : run.index("$stamp =")]
    assert "if ($licence.Kind -eq 'warn')" in guard
    assert "Infrastructure fault:" in guard and "The 90-day rebuild" in guard
    assert "exit 1" in guard


def test_the_expiry_state_refuses_a_passed_date_and_warns_within_14_days() -> None:
    cases = {
        "past": '"2026-11-12T23:59:00Z"',
        "now": '"2026-11-13T00:00:00Z"',
        "d10": '"2026-11-23T00:00:00Z"',
        "d14": '"2026-11-27T00:00:00Z"',
        "d15": '"2026-11-28T00:00:00Z"',
        "none": "null",
    }
    script = ["$now = [DateTime]::new(2026, 11, 13, 0, 0, 0, [DateTimeKind]::Utc)"]
    for value in cases.values():
        json = f'{{"licence_source": "evaluation", "licence_expires": {value}}}'
        script.append(f"(Get-NativeE2eLicenceState ('{json}' | ConvertFrom-Json) $now).Kind")
    script.append(
        '(Get-NativeE2eLicenceState (\'{"licence_source": "key"}\' | ConvertFrom-Json) $now).Kind'
    )
    script.append("(Get-NativeE2eLicenceState ('{}' | ConvertFrom-Json) $now).Kind")
    kinds = powershell("; ".join(script))
    assert kinds == ["expired", "expired", "warn", "warn", "ok", "unknown", "none", "unknown"]


def test_the_media_check_refuses_a_licence_source_mismatch() -> None:
    script = """
    $eval = [pscustomobject]@{ EditionId = 'EnterpriseEval'; ImageName = 'Windows 11 Enterprise Evaluation' }
    $full = [pscustomobject]@{ EditionId = 'Professional'; ImageName = 'Windows 11 Pro' }
    foreach ($case in @(@('evaluation', $eval), @('key', $full), @('key', $eval), @('evaluation', $full))) {
        try { Assert-NativeE2eLicenceMedia $case[0] $case[1]; 'ok' } catch { 'refused' }
    }
    """
    assert powershell(script) == ["ok", "ok", "refused", "refused"]


def test_the_setup_doc_covers_the_licence_runbook() -> None:
    text = " ".join((ROOT / "docs" / "native-e2e-setup.md").read_text(encoding="utf-8").split())
    for topic in (
        "-LicenceSource key",
        "activation-allowlist.txt",
        "licence_expires",
        "14 days",
        "CRL",
        "OCSP",
        "never a script argument",
    ):
        assert topic in text, topic
