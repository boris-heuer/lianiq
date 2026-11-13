"""Static checks of the native-e2e image, run and guest scripts (CAP-0174 WI-02).

The scripts act on Hyper-V and a VM, so they never run here: these checks read the files
and pin the contract section 4 and 4.4 choices that a reviewer would otherwise check by eye.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools" / "native-e2e"
HOST = TOOLS / "host"
GUEST = TOOLS / "guest"
NATIVE_LOCK = ROOT / "native_e2e" / "requirements-native-lock.txt"
SCOPE = [
    HOST / "New-NativeE2eImage.ps1",
    HOST / "Invoke-NativeE2eRun.ps1",
    HOST / "egress-proxy.py",
    HOST / "egress-allowlist.txt",
    GUEST / "provision.ps1",
    GUEST / "admin-helper.ps1",
    GUEST / "runner-logon.ps1",
    GUEST / "autounattend.xml",
    ROOT / "native_e2e" / "data" / "make_test_phrase.py",
    NATIVE_LOCK,
    ROOT / "docs" / "native-e2e-setup.md",
]
MAX_PY_BYTES = 12_288
MAX_TEXT_BYTES = 22_000


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def code(path: Path) -> str:
    """PowerShell source without comment-help blocks and line comments."""
    text = re.sub(r"<#.*?#>", "", read(path), flags=re.DOTALL)
    lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    return "\n".join(line.split(" #", 1)[0] for line in lines)


def test_every_wi02_file_exists() -> None:
    assert [path for path in SCOPE if not path.is_file()] == []


def test_files_are_small_utf8_text_and_powershell_is_ascii() -> None:
    files = [p for p in [*TOOLS.rglob("*"), *(ROOT / "native_e2e").rglob("*")] if p.is_file()]
    files = [p for p in files if "__pycache__" not in p.parts]
    for path in files:
        data = path.read_bytes()
        data.decode("utf-8")  # no binary file is committed
        limit = MAX_PY_BYTES if path.suffix == ".py" else MAX_TEXT_BYTES
        assert len(data) <= limit, path
        if path.suffix == ".ps1":
            assert data.isascii(), path  # Windows PowerShell 5.1 reads BOM-less files as ANSI
        assert path.suffix not in {".wav", ".png", ".zip", ".exe"}, path


def test_no_test_phrase_wav_is_committed() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "--", "*.wav"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    assert tracked.stdout.strip() == ""


def test_admin_helper_executes_exactly_the_three_contract_verbs() -> None:
    source = code(GUEST / "admin-helper.ps1")
    verbs = re.search(r"\$AllowedVerbs = @\(([^)]*)\)", source)
    assert verbs is not None
    assert re.findall(r"'([^']+)'", verbs.group(1)) == [
        "firewall-block-app",
        "firewall-unblock-app",
        "wfp-count",
    ]
    branches = re.findall(r"^\s+'([a-z-]+)' \{", source, flags=re.MULTILINE)
    assert branches == ["firewall-block-app", "firewall-unblock-app", "wfp-count"]
    assert "switch -CaseSensitive" in source and "-cnotcontains $verb" in source
    assert "default { return (New-VerbResult $false $null 'verb-not-allowed') }" in source
    # The path argument is pinned to the image.json interpreter; the rule name is fixed.
    assert "image.json" in source and "$image.interpreter" in source
    assert source.count("Test-PinnedPath $Arguments[0] $Pinned") == 2
    assert "$RuleName = 'lianiq-e2e-block-app'" in source
    assert "-Program $Pinned" in source
    assert "Invoke-Expression" not in source and "Start-Process" not in source
    assert "Id = 5156, 5157" in source


def test_runner_and_helper_tasks_run_as_the_intended_principals() -> None:
    source = code(GUEST / "provision.ps1")
    assert "New-ScheduledTaskPrincipal -UserId 'S-1-5-18' -LogonType ServiceAccount" in source
    assert "-LogonType Interactive -RunLevel Limited" in source
    assert "-AtLogOn -User $account" in source
    assert "$TestUser = 'e2e'" in source
    assert "'The test user must not be an administrator.'" in source
    assert "-SID 'S-1-5-32-544' -Member" not in source  # e2e is never added to Administrators
    assert "'AutoAdminLogon' '1'" in source and "'DefaultUserName' $TestUser" in source
    assert "SetEnvironmentVariable('https_proxy', $proxy, 'Machine')" in source
    assert "{0CCE9226-69AE-11D9-BED3-505054503030}" in source
    assert "--no-index" in source and "--require-hashes" in source
    assert "requirements-native-lock.txt" in source
    assert "make_test_phrase.py" in source and "test_phrase" in source
    assert "models_manifest_sha256" in source and "interpreter            = $Interpreter" in source
    assert "Disable-LocalUser" in source and "Panther\\unattend.xml" in source


def test_runner_logon_starts_a_jit_runner_once_and_never_logs_the_config() -> None:
    source = code(GUEST / "runner-logon.ps1")
    assert "--jitconfig $config" in source
    assert "Remove-Item -LiteralPath $JitPath" in source
    assert "config.cmd" not in source and "svc" not in source  # not a service, no token
    for line in source.splitlines():
        if "Write-LogonLog" in line and "function" not in line:
            assert "$config" not in line


def test_image_build_is_offline_isolated_and_matches_the_image_spec() -> None:
    source = code(HOST / "New-NativeE2eImage.ps1") + code(HOST / "NativeE2e.Image.ps1")
    assert "New-VMSwitch -Name $SwitchName -SwitchType Internal" in source
    assert "New-NetNat" not in source and "External" not in source
    assert "Expand-WindowsImage" in source and "Panther" in source
    assert "-Generation 2 -MemoryStartupBytes 8GB" in source and "-ProcessorCount 4" in source
    assert "-HorizontalResolution 1920 -VerticalResolution 1080" in source
    assert "-EnableSecureBoot On" in source and "Enable-VMTPM" in source
    assert "-AutomaticCheckpointsEnabled $false" in source
    assert "Checkpoint-VM -Name $VmName -SnapshotName $script:NativeE2eCheckpoint" in source
    assert "scripts\\download_models.py" in source and "--require-hashes" in source
    assert "Set-NativeE2eAdapterAcls" in source
    assert "Add-VMDvdDrive" not in source and "Set-VMHost" not in source


def test_adapter_acls_deny_everything_but_the_proxy_port() -> None:
    source = code(HOST / "NativeE2e.Host.ps1")
    acls = [
        line.strip() for line in source.splitlines() if "Add-VMNetworkAdapterExtendedAcl" in line
    ]
    assert len(acls) == 3
    assert any("-Action Deny -Direction Outbound -Weight 1" in line for line in acls)
    assert any("-Action Deny -Direction Inbound -Weight 1" in line for line in acls)
    allow = source[source.index("-Action Allow -Direction Outbound") :]
    assert "-RemoteIPAddress $HostAddress -RemotePort ([string]$ProxyPort) -Protocol 'TCP'" in allow
    assert "-Weight 100 -Stateful $true" in allow
    assert "$script:NativeE2eRepository = 'boris-heuer/lianiq'" in source
    assert "@('self-hosted', 'windows', 'win11-native-e2e')" in source


def test_the_answer_file_is_well_formed_with_placeholders_only() -> None:
    text = read(GUEST / "autounattend.xml")
    root = ElementTree.fromstring(text.encode("utf-8"))
    assert root.tag == "{urn:schemas-microsoft-com:unattend}unattend"
    values = [node.text for node in root.iter("{urn:schemas-microsoft-com:unattend}Value")]
    assert values == ["@@ADMIN_PASSWORD@@", "@@ADMIN_PASSWORD@@"]
    assert "setup\\provision.ps1" in text
    assert "<LogonCount>1</LogonCount>" in text


def test_the_native_lock_is_pinned_and_hashed() -> None:
    text = read(NATIVE_LOCK)
    pin = r"^([a-z0-9-]+)==(\S+) \\\n((?:\s+--hash=sha256:[0-9a-f]{64}.*\n)+)"
    pins = re.findall(pin, text, re.MULTILINE)
    names = [name for name, _version, _hashes in pins]
    assert names == sorted(names)
    assert {"pywinauto", "psutil", "comtypes", "pywin32"} <= set(names)
    requirement_lines = [line for line in text.splitlines() if re.match(r"^[A-Za-z0-9]", line)]
    assert len(requirement_lines) == len(pins)  # every requirement carries a hash
    main_lock = read(ROOT / "requirements-lock.txt")
    for name, _version, _hashes in pins:
        assert not re.search(rf"^{re.escape(name)}==", main_lock, re.MULTILINE), name


def test_the_setup_doc_covers_every_ac20_topic() -> None:
    text = " ".join(read(ROOT / "docs" / "native-e2e-setup.md").split())
    for topic in (
        "## Prerequisites",
        "Hyper-V",
        "evaluation ISO",
        "VB-Cable",
        "donationware",
        "## Build the image",
        "## Per-run steps",
        "90 days",
        "## Approve the run",
        "## Troubleshooting",
        "## Security boundary",
        "-NoRevert",
        "New-NativeE2eImage.ps1",
        "Invoke-NativeE2eRun.ps1",
        "egress-allowlist.txt",
    ):
        assert topic in text, topic
