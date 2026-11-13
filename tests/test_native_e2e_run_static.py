"""Static checks of the native-e2e run script and host guards (CAP-0174 WI-02).

The run script drives Hyper-V and the GitHub API, so it never runs here. These checks pin
spec section 2.2.2: a failed runner-state read is never taken as a finished job, every
cleanup step runs, and the network guard fails closed.
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


def function(source: str, name: str) -> str:
    start = source.index(f"function {name}")
    end = source.find("\nfunction ", start + 1)
    return source[start : end if end != -1 else len(source)]


RUN = code(HOST / "Invoke-NativeE2eRun.ps1")


def test_the_run_script_reverts_injects_after_heartbeat_and_honours_no_revert() -> None:
    assert re.search(r"param\(\s*\[switch\]\$NoRevert", RUN)
    order = [
        "Assert-NativeE2eNetwork $state",
        "Restore-Clean $vm",
        "Start-EgressProxy $state",
        "Start-VM -Name $vm",
        "'VM heartbeat'",
        "actions/runners/generate-jitconfig",
        "Copy-JitConfig $vm",
        "'runner online'",
        "'job completion'",
        "'Shutting the VM down'",
    ]
    positions = [RUN.index(marker) for marker in order]
    assert positions == sorted(positions)
    assert "Copy-VMFile -Name $VmName -SourcePath $file -DestinationPath $JitDestination" in RUN
    assert "-FileSource Host" in RUN
    assert RUN.count("if ($NoRevert)") == 2  # start and end revert are both skipped
    assert "Restore-VMSnapshot -VMName $VmName -Name $script:NativeE2eCheckpoint" in RUN
    assert "encoded_jit_config" in RUN and "Write-Host $jit" not in RUN


def test_runner_state_tells_a_404_from_any_other_error() -> None:
    state = function(RUN, "Get-RunnerState")
    assert "Invoke-NativeE2eGhRaw @('api', \"repos/$Repo/actions/runners/$RunnerId\")" in state
    assert "$code = $result.ExitCode" in state
    assert "if (\"$($result.Err)`n$($result.Out)\" -match 'HTTP 404')" in state
    assert re.findall(r"Kind = '([a-z]+)'", state) == ["runner", "error", "gone", "error"]
    assert "return $null" not in state


def test_only_a_404_or_idle_after_busy_finishes_the_job() -> None:
    finished = function(RUN, "Test-JobFinished")
    body = [line.strip() for line in finished.splitlines()[1:] if line.strip() not in {"", "}"}]
    assert body == [
        "if (-not $SawBusy) { return $false }",
        "if ($Probe.Kind -eq 'gone') { return $true }",
        "return $Probe.Kind -eq 'runner' -and -not $Probe.Runner.busy",
    ]
    wait = RUN[RUN.index("$script:sawBusy = $false") : RUN.index("'job completion'")]
    lines = [line.strip() for line in wait.splitlines() if line.strip()]
    assert lines[-1].startswith("} ($JobTimeoutMinutes")
    assert lines[-2] == "Test-JobFinished $probe $script:sawBusy"  # the loop's only exit value
    assert "$null -eq $runner" not in RUN and "$null -eq $probe" not in RUN
    assert 'Write-Warning "Runner state unavailable: $($probe.Message)"' in wait
    assert (
        "if ($probe.Kind -eq 'runner' -and $probe.Runner.busy) { $script:sawBusy = $true }" in wait
    )


def test_a_missed_deadline_is_an_infrastructure_fault() -> None:
    assert "the job did not finish within $JobTimeoutMinutes minutes." in RUN
    assert "the runner did not come online within $RunnerOnlineMinutes minutes." in RUN
    assert "the runner disappeared before it took a job." in RUN
    assert "$exitCode = 1" in RUN and RUN.rstrip().endswith("exit $exitCode")


def test_every_cleanup_step_runs_and_a_failed_one_fails_the_script() -> None:
    cleanup = RUN[RUN.index("} finally {") :]
    for step in ("'remove runner'", "'stop VM'", "'stop proxy'", "'revert'"):
        assert f"Invoke-Cleanup {step}" in cleanup, step
    assert "Stop-Process -Id $proxy.Id -Force" in cleanup
    assert "if ($exitCode -eq 0) { $exitCode = 3 }" in cleanup
    guarded = function(RUN, "Invoke-Cleanup")
    assert "try {" in guarded and "return $false" in guarded
    stop = function(RUN, "Stop-Guest")
    assert stop.index("catch") < stop.index("-TurnOff")  # a failed shutdown still turns off


def test_the_network_guard_is_exact_and_fails_closed() -> None:
    helper = code(HOST / "NativeE2e.Host.ps1")
    guard = function(helper, "Assert-NativeE2eNetwork")
    assert "-like" not in guard
    assert "$hostTargets -contains [string]$allow[0].RemoteIPAddress" in guard
    assert "Where-Object $unscoped" in guard and "$deny.Count -ne 2" in guard
    for field in ("LocalIPAddress", "RemoteIPAddress", "LocalPort", "RemotePort", "Protocol"):
        assert f"Test-NativeE2eUnscoped ([string]$_.{field})" in guard, field
    assert "Assert-NativeE2eNoNat $prefix" in guard
    nat = function(helper, "Assert-NativeE2eNoNat")
    assert "Test-NativeE2ePrefixOverlap" in nat and "-eq $prefix" not in nat
    overlap = function(helper, "Test-NativeE2ePrefixOverlap")
    assert "[Math]::Min([int]$aLength, [int]$bLength)" in overlap
    assert "{ return $true }" in overlap  # an unparsable NAT prefix counts as covering
    image = code(HOST / "NativeE2e.Image.ps1")
    assert "Assert-NativeE2eNoNat $prefix" in image and "Get-NetNat" not in image


def test_the_host_state_folder_is_admin_only() -> None:
    image = code(HOST / "New-NativeE2eImage.ps1")
    acl = "icacls.exe $StateRoot /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F'"
    assert acl in image
    assert image.index(acl) < image.index("Get-PythonInstaller $payload")


def test_the_admin_helper_never_spins_on_a_bad_request_or_a_missing_folder() -> None:
    helper = code(GUEST / "admin-helper.ps1")
    assert "try { Invoke-Request $file $pinned } catch { Remove-BadRequest $file }" in helper
    bad = function(helper, "Remove-BadRequest")
    assert "Remove-Item -LiteralPath $File.FullName" in bad
    assert "if ($script:Skipped.Add($key))" in bad  # logged once, then skipped
    assert "-not $script:Skipped.Contains(" in helper
    assert "{ Restore-RequestDir }" in helper
    restore = function(helper, "Restore-RequestDir")
    assert '"${user}:(OI)(CI)M"' in restore and "test_user" in restore


def enclosing_function(source: str, index: int) -> tuple[str, str] | None:
    """Name and body of the function whose braces contain ``index``, if any."""
    for match in re.finditer(r"^function ([\w-]+)[^\n]*?\{", source, flags=re.MULTILINE):
        depth, end = 0, match.end() - 1
        for end in range(match.end() - 1, len(source)):
            depth += {"{": 1, "}": -1}.get(source[end], 0)
            if depth == 0:
                break
        if match.start() < index < end:
            return match.group(1), source[match.start() : index]
    return None


def test_native_stderr_is_redirected_only_where_errors_continue() -> None:
    # Windows PowerShell 5.1 turns redirected native stderr into terminating errors under
    # $ErrorActionPreference = 'Stop', so a 404 from gh would never reach its branch.
    scripts = sorted([*HOST.glob("*.ps1"), *GUEST.glob("*.ps1")])
    redirects = 0
    for path in scripts:
        source = code(path)
        for match in re.finditer(r"2>", source):
            redirects += 1
            found = enclosing_function(source, match.start())
            assert found is not None, f"{path.name}: stderr redirect outside a function"
            assert "$ErrorActionPreference = 'Continue'" in found[1], (path.name, found[0])
    assert redirects >= 1
    calls = [
        (path.name, enclosing_function(code(path), match.start()))
        for path in scripts
        for match in re.finditer(r"&\s*gh\b", code(path))
    ]
    assert [(name, found and found[0]) for name, found in calls] == [
        ("NativeE2e.Host.ps1", "Invoke-NativeE2eGhRaw")
    ]


def test_a_404_before_busy_checks_for_a_finished_run_first() -> None:
    wait = RUN[RUN.index("$script:sawBusy = $false") : RUN.index("'job completion'")]
    gone = wait[wait.index("if ($probe.Kind -eq 'gone' -and -not $script:sawBusy)") :]
    assert gone.index("Find-Run $runnerName") < gone.index("the runner disappeared")
    assert "$script:sawBusy = $true" in gone
    image = code(HOST / "New-NativeE2eImage.ps1")
    assert "icacls.exe $StateRoot /setowner '*S-1-5-32-544'" in image
