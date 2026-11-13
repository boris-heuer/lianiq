"""Static checks of the MinGit payload of the native-e2e image (CAP-0174 WI-03).

S-01 runs ``git rev-parse HEAD`` and ``git for-each-ref --contains`` in the guest, and
``actions/checkout`` clones with Git only when it finds it on PATH. The image therefore
carries a pinned, hash-checked MinGit, extracted offline and put on PATH for the runner
process only. The scripts act on Hyper-V and a VM, so these checks read the files.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "tools" / "native-e2e" / "host"
GUEST = ROOT / "tools" / "native-e2e" / "guest"
WORKFLOW = ROOT / ".github" / "workflows" / "native-e2e.yml"
TAG = "v2.56.0.windows.4"
ASSET = "MinGit-2.56.0.4-64-bit.zip"
URL = f"https://github.com/git-for-windows/git/releases/download/{TAG}/{ASSET}"
NOCASE = re.IGNORECASE
SHA256 = "e3bf78351fe777fba47ddee5950082f8a98bb0f02604fdc7ba3ee2cb68ffa877"


def code(path: Path) -> str:
    """PowerShell source without comment-help blocks and line comments."""
    text = re.sub(r"<#.*?#>", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
    lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    return "\n".join(line.split(" #", 1)[0] for line in lines)


IMAGE = code(HOST / "New-NativeE2eImage.ps1")
PROVISION = code(GUEST / "provision.ps1")
LOGON = code(GUEST / "runner-logon.ps1")


def function(source: str, name: str) -> str:
    start = source.index(f"function {name}")
    end = source.find("\nfunction ", start + 1)
    return source[start : end if end > 0 else len(source)]


def test_the_host_pins_the_mingit_release_asset_url_and_hash() -> None:
    assert f"$MinGitTag = '{TAG}'" in IMAGE
    assert f"$MinGitAsset = '{ASSET}'" in IMAGE
    assert f"$MinGitUrl = '{URL}'" in IMAGE
    assert f"$MinGitSha256 = '{SHA256}'" in IMAGE
    assert IMAGE.count(SHA256) == 1  # one pin, compared with the digest and the file


def test_the_host_checks_the_download_against_the_pin_and_the_release_digest() -> None:
    body = function(IMAGE, "Get-MinGitPackage")
    assert "'repos/git-for-windows/git/releases/tags/' + $MinGitTag" in body
    assert "$_.name -ceq $MinGitAsset" in body
    assert '[string]$asset[0].digest -cne "sha256:$MinGitSha256"' in body
    assert "[string]$asset[0].browser_download_url -cne $MinGitUrl" in body
    assert "'release', 'download', $MinGitTag, '--repo', 'git-for-windows/git'" in body
    assert "$sha -cne $MinGitSha256" in body
    assert body.count("throw ") >= 2  # a release or a download mismatch refuses the build
    # The digest is checked before the download, the file hash after it.
    assert body.index("digest -cne") < body.index("'release', 'download'") < body.index("$sha -cne")
    assert "return [ordered]@{ file = $MinGitAsset; version = $MinGitVersion; sha256 = $sha }" in (
        body
    )
    assert "$minGit = Get-MinGitPackage $payload" in IMAGE


def test_the_build_manifest_records_the_mingit_file_version_and_hash() -> None:
    assert re.search(r"^\s+mingit\s+= \$minGit$", IMAGE, re.MULTILINE)
    assert re.search(r"^\s+mingit_version\s+= \$minGit\.version$", IMAGE, re.MULTILINE)
    assert re.search(r"^\s+mingit_sha256\s+= \$minGit\.sha256$", IMAGE, re.MULTILINE)


def test_the_guest_extracts_mingit_offline_into_a_fixed_readable_folder() -> None:
    assert "$MinGitDir = Join-Path $Root 'mingit'" in PROVISION
    assert "$GitExe = Join-Path $MinGitDir 'cmd\\git.exe'" in PROVISION
    step = PROVISION[PROVISION.index("Invoke-Step 'mingit'") :]
    step = step[: step.index("Invoke-Step", 10)]
    assert "Join-Path $Setup $inputs.mingit.file" in step
    assert "(Get-FileSha256 $package) -cne $inputs.mingit.sha256" in step
    assert "Expand-Archive -LiteralPath $package -DestinationPath $MinGitDir" in step
    assert "& $GitExe --version" in step and "$inputs.mingit.version" in step
    assert "Invoke-WebRequest" not in PROVISION  # offline
    # The folder sits under the root, which grants Users read and execute only.
    assert PROVISION.index("Invoke-Step 'folders'") < PROVISION.index("Invoke-Step 'mingit'")
    assert re.search(r"^\s+git\s+= \$GitExe$", PROVISION, re.MULTILINE)
    assert re.search(r"^\s+git_version\s+= \$inputs\.mingit\.version$", PROVISION, re.MULTILINE)
    assert "$inputs.mingit.file" in PROVISION[PROVISION.index("Invoke-Step 'cleanup'") :]


def test_no_guest_script_changes_the_machine_or_user_path() -> None:
    for path in sorted(GUEST.glob("*.ps1")):
        source = code(path)
        assert not re.search(r"SetEnvironmentVariable\(\s*['\"]path['\"]", source, NOCASE), path
        assert not re.search(r"\bsetx(\.exe)?\b", source, NOCASE), path
        assert not re.search(r"Session Manager\\+Environment", source, NOCASE), path
        assert not re.search(r"HKCU:\\+Environment", source, NOCASE), path
        assert not re.search(r"\$env:path\s*=", source, NOCASE) or path.name == "runner-logon.ps1"


def test_the_runner_alone_gets_mingit_on_path_before_it_starts() -> None:
    assert "$MinGitCmd = Join-Path $Root 'mingit\\cmd'" in LOGON
    prepend = '$env:PATH = "$MinGitCmd;$env:PATH"'
    assert LOGON.count(prepend) == 1
    assert LOGON.index(prepend) < LOGON.index("& $runner --jitconfig $config")
    assert "Test-Path -LiteralPath (Join-Path $MinGitCmd 'git.exe')" in LOGON


def test_the_checkout_fetches_every_branch_and_keeps_the_git_guard() -> None:
    steps = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["native"]["steps"]
    uses = [
        i for i, item in enumerate(steps) if item.get("uses", "").startswith("actions/checkout")
    ]
    assert len(uses) == 1
    checkout = steps[uses[0]]
    assert checkout["with"]["fetch-depth"] == 0
    assert checkout["with"]["persist-credentials"] is False
    guard = steps[0]["run"]
    assert "Get-Command git -ErrorAction SilentlyContinue" in guard
    assert "Stop-Run 'git-not-available'" in guard and uses[0] > 0
    shot = (ROOT / "native_e2e" / "rows" / "shot.py").read_text(encoding="utf-8")
    assert '"origin/main:' in shot and '"show"' in shot


def test_the_docs_and_changelog_name_mingit_and_its_licence() -> None:
    doc = " ".join((ROOT / "docs" / "native-e2e-setup.md").read_text(encoding="utf-8").split())
    for topic in (ASSET, TAG, SHA256, "GPLv2", "### MinGit licence", "not distributed"):
        assert topic in doc, topic
    assert "C:\\ProgramData\\lianiq-e2e\\mingit" in doc
    assert "machine `PATH`" in doc
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "MinGit" in changelog[: changelog.index("### Changed")]
