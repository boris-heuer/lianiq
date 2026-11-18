"""Checks of scripts/install-release.ps1: version validation, path safety, shortcut target.

The functions are dot-sourced into Windows PowerShell; nothing is cloned, built or installed.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install-release.ps1"
POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")

needs_powershell = pytest.mark.skipif(
    sys.platform != "win32" or POWERSHELL is None, reason="needs Windows PowerShell"
)


def run_ps(body: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Dot-source the script, then run ``body``; extra args go to the script's parameters."""
    script_args = " ".join(args)
    command = f"[Console]::OutputEncoding = [Text.Encoding]::UTF8; $ErrorActionPreference = 'Stop'; . '{SCRIPT}' {script_args}; {body}"
    assert POWERSHELL is not None
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command"]
        + [command],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )


def ps_ok(body: str, *args: str) -> str:
    result = run_ps(body, *args)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_script_is_ascii() -> None:
    # Windows PowerShell 5.1 reads BOM-less files as ANSI.
    assert SCRIPT.read_bytes().isascii()


def test_script_never_pushes_or_needs_admin() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "RunAs" not in text
    assert "git push" not in text
    assert "HKLM" not in text


@needs_powershell
@pytest.mark.parametrize("version", ["v0.2.0", "v1.10.3", "v0.0.0"])
def test_valid_versions_are_accepted(version: str) -> None:
    ps_ok(f"Assert-LianiqVersion '{version}'")


@needs_powershell
@pytest.mark.parametrize(
    "version",
    [
        "",
        "0.2.0",
        "v0.2",
        "v0.2.0.1",
        "v01.2.0",
        "V0.2.0",
        "v0.2.0-rc1",
        "v0.2.0;x",
        "..\\v0.2.0",
        "v0.2.0\\..",
    ],
)
def test_invalid_versions_are_rejected(version: str) -> None:
    result = run_ps(f"Assert-LianiqVersion '{version}'")
    assert result.returncode != 0
    assert "Invalid version" in result.stderr


@needs_powershell
def test_child_path_stays_directly_under_root(tmp_path: Path) -> None:
    out = ps_ok(f"Resolve-ChildPath '{tmp_path}' 'v0.2.0'")
    assert Path(out) == tmp_path / "v0.2.0"
    for name in ["..\\evil", ".", "..", "a\\b", "C:\\Windows", ""]:
        result = run_ps(f"Resolve-ChildPath '{tmp_path}' '{name}'")
        assert result.returncode != 0, name
        assert "Unsafe path" in result.stderr, name


def _install(root: Path, version: str, *, exe: bool = True) -> None:
    folder = root / version
    folder.mkdir(parents=True)
    if exe:
        (folder / "lianiq.exe").write_bytes(b"")


@needs_powershell
def test_shortcut_target_is_newest_version_with_an_exe(tmp_path: Path) -> None:
    for version in ["v0.1.0", "v0.2.0", "v0.10.0"]:
        _install(tmp_path, version)
    _install(tmp_path, "v9.0.0", exe=False)  # incomplete install is ignored
    _install(tmp_path, ".staging-v99.0.0")
    _install(tmp_path, "notes")
    out = ps_ok(f"(Get-ShortcutTarget '{tmp_path}').Exe")
    assert Path(out) == tmp_path / "v0.10.0" / "lianiq.exe"


@needs_powershell
def test_shortcut_target_fails_without_any_install(tmp_path: Path) -> None:
    result = run_ps(f"Get-ShortcutTarget '{tmp_path}'")
    assert result.returncode != 0
    assert "No installed Lianiq version" in result.stderr


@needs_powershell
def test_shortcut_points_at_newest_exe(tmp_path: Path) -> None:
    root = tmp_path / "programs"
    _install(root, "v0.1.0")
    _install(root, "v0.2.0")
    links = tmp_path / "links"
    out = ps_ok(
        f"$link = Set-LianiqShortcut '{links}' 'Lianiq' (Get-ShortcutTarget '{root}'); "
        "$s = New-Object -ComObject WScript.Shell; $l = $s.CreateShortcut($link); "
        "$l.TargetPath; $l.WorkingDirectory"
    )
    target, workdir = out.splitlines()
    assert (links / "Lianiq.lnk").is_file()
    assert Path(target) == root / "v0.2.0" / "lianiq.exe"
    assert Path(workdir) == root / "v0.2.0"


@needs_powershell
def test_existing_version_is_not_overwritten_without_force(tmp_path: Path) -> None:
    root = tmp_path / "programs"
    _install(root, "v0.2.0")
    build = tmp_path / "build"
    result = run_ps(
        "Install-LianiqRelease",
        "-Version v0.2.0",
        f"-InstallRoot '{root}'",
        f"-BuildRoot '{build}'",
        f"-RepositoryUrl '{tmp_path / 'no-such-repo'}'",
    )
    assert result.returncode != 0
    assert "already installed" in result.stderr
    assert not build.exists()  # refused before any clone


@needs_powershell
def test_local_settings_are_carried_over(tmp_path: Path) -> None:
    old = tmp_path / "v0.1.0"
    (old / "config").mkdir(parents=True)
    (old / "config" / "settings.local.json").write_text("{}", encoding="utf-8")
    (old / "config" / "settings.json").write_text("default", encoding="utf-8")
    new = tmp_path / "v0.2.0"
    new.mkdir()
    ps_ok(f"Copy-LocalSettings '{old}' '{new}'")
    assert (new / "config" / "settings.local.json").read_text(encoding="utf-8") == "{}"
    assert not (new / "config" / "settings.json").exists()  # shipped defaults are not copied


@needs_powershell
@pytest.mark.parametrize("name", [".. ", ". .", "..\t"])
def test_child_path_rejects_names_that_resolve_to_the_root(tmp_path: Path, name: str) -> None:
    result = run_ps(f"Resolve-ChildPath '{tmp_path}' \"{name}\"")
    assert result.returncode != 0
    assert "Unsafe path" in result.stderr


@needs_powershell
def test_existing_build_folder_is_not_reused_without_force(tmp_path: Path) -> None:
    build = tmp_path / "build"
    (build / "v0.2.0").mkdir(parents=True)
    result = run_ps(
        "Install-LianiqRelease",
        "-Version v0.2.0",
        f"-InstallRoot '{tmp_path / 'programs'}'",
        f"-BuildRoot '{build}'",
        f"-RepositoryUrl '{tmp_path / 'no-such-repo'}'",
    )
    assert result.returncode != 0
    assert "Build folder" in result.stderr
    assert list((build / "v0.2.0").iterdir()) == []  # left alone, nothing cloned


@needs_powershell
def test_failed_native_step_stops_the_install() -> None:
    result = run_ps("Invoke-Checked 'step' { cmd /c exit 3 }")
    assert result.returncode != 0
    assert "step failed (exit code 3)" in result.stderr


def _dist(tmp_path: Path, marker: str) -> Path:
    dist = tmp_path / f"dist-{marker}"
    (dist / "config").mkdir(parents=True)
    (dist / "lianiq.exe").write_text(marker, encoding="utf-8")
    (dist / "config" / "settings.json").write_text("default", encoding="utf-8")
    return dist


def _settings(folder: Path, text: str) -> None:
    (folder / "config").mkdir(parents=True, exist_ok=True)
    (folder / "config" / "settings.local.json").write_text(text, encoding="utf-8")


def _local(folder: Path) -> str:
    return (folder / "config" / "settings.local.json").read_text(encoding="utf-8")


@needs_powershell
def test_new_version_takes_settings_from_newest_install(tmp_path: Path) -> None:
    root = tmp_path / "programs"
    _install(root, "v0.1.0")
    _settings(root / "v0.1.0", "old")
    _install(root, "v0.1.5")
    _settings(root / "v0.1.5", "newest")
    ps_ok(f"Publish-LianiqInstall '{root}' 'v0.2.0' '{_dist(tmp_path, 'new')}'")
    assert (root / "v0.2.0" / "lianiq.exe").read_text(encoding="utf-8") == "new"
    assert _local(root / "v0.2.0") == "newest"
    assert _local(root / "v0.1.5") == "newest"  # older versions stay
    assert sorted(p.name for p in root.iterdir()) == ["v0.1.0", "v0.1.5", "v0.2.0"]


@needs_powershell
def test_forced_replace_keeps_the_replaced_versions_settings(tmp_path: Path) -> None:
    root = tmp_path / "programs"
    _install(root, "v0.2.0")
    _settings(root / "v0.2.0", "mine")
    _install(root, "v0.3.0")
    _settings(root / "v0.3.0", "other")
    ps_ok(f"Publish-LianiqInstall '{root}' 'v0.2.0' '{_dist(tmp_path, 'rebuilt')}'")
    assert (root / "v0.2.0" / "lianiq.exe").read_text(encoding="utf-8") == "rebuilt"
    assert _local(root / "v0.2.0") == "mine"
    assert sorted(p.name for p in root.iterdir()) == ["v0.2.0", "v0.3.0"]


@needs_powershell
def test_running_install_is_left_complete(tmp_path: Path) -> None:
    root = tmp_path / "programs"
    _install(root, "v0.2.0")
    _settings(root / "v0.2.0", "mine")
    exe = root / "v0.2.0" / "lianiq.exe"
    result = run_ps(
        f"$lock = [System.IO.File]::Open('{exe}', 'Open', 'Read', 'None'); "
        f"try {{ Publish-LianiqInstall '{root}' 'v0.2.0' '{_dist(tmp_path, 'new')}' }} "
        "finally { $lock.Dispose() }"
    )
    assert result.returncode != 0
    assert "still running" in result.stderr
    assert _local(root / "v0.2.0") == "mine"
    assert exe.read_bytes() == b""  # the old install is untouched


@needs_powershell
def test_interrupted_swap_is_restored_before_replacing(tmp_path: Path) -> None:
    root = tmp_path / "programs"
    _install(root, ".old-v0.2.0")
    _settings(root / ".old-v0.2.0", "mine")
    ps_ok(f"Publish-LianiqInstall '{root}' 'v0.2.0' '{_dist(tmp_path, 'new')}'")
    assert _local(root / "v0.2.0") == "mine"
    assert sorted(p.name for p in root.iterdir()) == ["v0.2.0"]


@needs_powershell
def test_failed_swap_puts_the_old_version_back(tmp_path: Path) -> None:
    root = tmp_path / "programs"
    _install(root, "v0.2.0")
    _settings(root / "v0.2.0", "mine")
    result = run_ps(
        "function Rename-Item { param([string]$LiteralPath, [string]$NewName) "
        "if ($LiteralPath -like '*.staging-*') { throw 'simulated lock' } "
        r"Microsoft.PowerShell.Management\Rename-Item -LiteralPath $LiteralPath -NewName $NewName }; "
        f"Publish-LianiqInstall '{root}' 'v0.2.0' '{_dist(tmp_path, 'new')}'"
    )
    assert result.returncode != 0
    assert "simulated lock" in result.stderr
    assert (root / "v0.2.0" / "lianiq.exe").read_bytes() == b""  # the old exe is back
    assert _local(root / "v0.2.0") == "mine"
    assert not (root / ".old-v0.2.0").exists()


@needs_powershell
def test_interrupted_swap_counts_as_installed(tmp_path: Path) -> None:
    root = tmp_path / "programs"
    _install(root, ".old-v0.2.0")
    build = tmp_path / "build"
    result = run_ps(
        "Install-LianiqRelease",
        "-Version v0.2.0",
        f"-InstallRoot '{root}'",
        f"-BuildRoot '{build}'",
        f"-RepositoryUrl '{tmp_path / 'no-such-repo'}'",
    )
    assert result.returncode != 0
    assert "already installed" in result.stderr
    assert not build.exists()
