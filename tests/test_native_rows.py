"""Unit tests of the S-01 and S-04 rows, the row order and the admin client (CAP-0174).

Portable halves of AC-09, AC-10 and AC-16: S-01 blocks a commit that no repository branch
contains, fails on a leftover run marker and writes the marker only on a clean start; S-04
passes only with the block rule, both rejected helper probes and zero counted attempts. The
helper itself is a SYSTEM task in the VM; here a thread answers its request files.
"""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

import pytest

from native_e2e import admin, runner, winenv
from native_e2e.context import RunContext
from native_e2e.evidence.model import Check, Method, Row, Status
from native_e2e.rows import s01, s04
from native_e2e.uia import wait_for

IMAGE = {
    "image": "win11-native-e2e@20261113",
    "image_id": "20261113",
    "models_manifest_sha256": "b" * 64,
    "interpreter": "C:\\Program Files\\Python312\\python.exe",
}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q")
    git(
        path,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "a",
    )
    git(path, "update-ref", "refs/remotes/origin/main", "HEAD")
    return path


def context(tmp_path: Path, repo: Path, commit: str) -> RunContext:
    root = tmp_path / "image"
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "image.json").write_text(json.dumps(IMAGE), encoding="utf-8")
    return RunContext(commit=commit, out=tmp_path / "out", repo=repo, image_root=root)


@pytest.fixture(autouse=True)
def build(monkeypatch) -> None:
    monkeypatch.setattr(winenv, "windows_build", lambda: "26100.4349")


def test_s01_passes_on_a_contained_commit_and_writes_the_marker(tmp_path, repo) -> None:
    ctx = context(tmp_path, repo, git(repo, "rev-parse", "HEAD"))
    row = s01.run(ctx)
    assert row.status is Status.PASS, row
    assert ctx.marker.is_file()
    assert ctx.state["environment"]["image"] == IMAGE["image"]
    assert ctx.state["environment"]["windows_build"] == "26100.4349"
    names = [check.name for check in row.checks]
    assert names[:2] == ["head-equals-commit", "commit-in-repository-branch"]
    assert "run-marker-absent" in names and "run-marker-written" in names


def test_s01_blocks_a_commit_that_no_repository_branch_contains(tmp_path, repo) -> None:
    git(
        repo,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "b",
    )
    ctx = context(tmp_path, repo, git(repo, "rev-parse", "HEAD"))  # only on the local branch
    row = s01.run(ctx)
    assert (row.status, row.reason) == (Status.BLOCKED, "commit-not-in-repository-branch")
    assert not ctx.marker.exists()


def test_s01_fails_on_a_leftover_marker_and_keeps_it(tmp_path, repo) -> None:
    ctx = context(tmp_path, repo, git(repo, "rev-parse", "HEAD"))
    ctx.marker.write_text('{"run": "previous"}', encoding="utf-8")
    row = s01.run(ctx)
    assert (row.status, row.reason) == (Status.FAIL, "not-clean-snapshot")
    assert ctx.marker.read_text(encoding="utf-8") == '{"run": "previous"}'


def test_s01_fails_when_head_is_not_the_commit(tmp_path, repo) -> None:
    ctx = context(tmp_path, repo, "f" * 40)
    row = s01.run(ctx)
    assert row.status is not Status.PASS
    assert not ctx.marker.exists()


def test_s01_fails_when_head_is_an_older_commit_than_a_contained_one(tmp_path, repo) -> None:
    first = git(repo, "rev-parse", "HEAD")
    git(
        repo,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "b",
    )
    second = git(repo, "rev-parse", "HEAD")
    git(repo, "update-ref", "refs/remotes/origin/main", second)
    git(repo, "checkout", "-q", "--detach", first)
    ctx = context(tmp_path, repo, second)  # in origin/main, but not HEAD
    row = s01.run(ctx)
    assert (row.status, row.reason) == (Status.FAIL, "head-differs-from-commit")
    assert row.checks[0] == Check("head-equals-commit", Status.FAIL)
    assert not ctx.marker.exists()


def fake(row_id: str, calls: list[str], status: Status = Status.PASS):
    def run(ctx) -> Row:
        calls.append(row_id)
        return Row(row_id, (), Method.NATIVE, status, (Check("x", status),), ())

    return run


def install(monkeypatch, calls: list[str], s01_status: Status = Status.PASS) -> None:
    from native_e2e.rows import c03, c04, e12, s02, s03, s05, shot, teardown

    monkeypatch.setattr(s01, "run", fake("S-01", calls, s01_status))
    for module, row_id in ((s02, "S-02"), (s03, "S-03"), (s05, "S-05"), (c04, "C-04")):
        monkeypatch.setattr(module, "run", fake(row_id, calls))
    for module, row_id in ((e12, "E-12"), (c03, "C-03"), (shot, "SHOT")):
        monkeypatch.setattr(module, "run", fake(row_id, calls))
    monkeypatch.setattr(s04, "begin", lambda ctx: calls.append("S-04 begin"))
    monkeypatch.setattr(s04, "finish", fake("S-04", calls))
    teardown_ids = ("T-01", "T-02", "T-03", "T-04")
    monkeypatch.setattr(teardown, "run", lambda ctx: [fake(t, calls)(ctx) for t in teardown_ids])


def test_rows_run_in_the_spec_order_with_the_s04_window_around_the_app_rows(
    tmp_path, monkeypatch, repo
) -> None:
    calls: list[str] = []
    install(monkeypatch, calls)
    rows = runner.execute(context(tmp_path, repo, "a" * 40))
    assert calls == [
        "S-01", "S-02", "S-03", "S-04 begin", "S-05", "C-04", "E-12", "C-03", "SHOT",
        "S-04", "T-01", "T-02", "T-03", "T-04",
    ]  # fmt: skip
    assert set(rows) == {c for c in calls if c != "S-04 begin"}


@pytest.mark.parametrize("status", [Status.BLOCKED, Status.FAIL])
def test_no_later_row_runs_when_s01_does_not_pass(tmp_path, monkeypatch, repo, status) -> None:
    calls: list[str] = []
    install(monkeypatch, calls, status)
    rows = runner.execute(context(tmp_path, repo, "a" * 40))
    assert calls == ["S-01"] and list(rows) == ["S-01"]


def test_a_raising_row_fails_without_its_message_and_teardown_still_runs(
    tmp_path, monkeypatch, repo
) -> None:
    from native_e2e.rows import c04

    calls: list[str] = []
    install(monkeypatch, calls)

    def boom(ctx) -> Row:
        raise OSError("C:\\Users\\someone\\secret")

    monkeypatch.setattr(c04, "run", boom)
    rows = runner.execute(context(tmp_path, repo, "a" * 40))
    assert rows["C-04"].status is Status.FAIL
    assert rows["C-04"].checks == (Check("unexpected-error", Status.FAIL, "OSError"),)
    assert calls[-4:] == ["T-01", "T-02", "T-03", "T-04"]


def helper(root: Path, answers: dict[str, dict], stop: threading.Event) -> None:
    while not stop.is_set():
        for request in (root / "requests").glob("*.json"):
            data = json.loads(request.read_text(encoding="utf-8"))
            request.unlink()
            reply = {"id": data["id"], "verb": data["verb"], **answers[data["verb"]]}
            (root / "results" / f"{data['id']}.json").write_text(json.dumps(reply), "utf-8")
        stop.wait(0.01)


@pytest.fixture
def helper_root(tmp_path, monkeypatch):
    root = tmp_path / "admin"
    (root / "requests").mkdir(parents=True)
    (root / "results").mkdir()
    monkeypatch.setattr(admin, "ADMIN_DIR", root)
    return root


def test_admin_request_writes_one_request_file_and_reads_the_result(helper_root) -> None:
    stop = threading.Event()
    answers = {"wfp-count": {"ok": True, "value": "0", "error": None}}
    thread = threading.Thread(target=helper, args=(helper_root, answers, stop), daemon=True)
    thread.start()
    try:
        result = admin.admin_request("wfp-count", "C:\\x.exe", "2026-11-13T00:00:00Z", timeout_s=5)
    finally:
        stop.set()
        thread.join()
    assert result == admin.AdminResult(True, "0", None)
    assert list((helper_root / "requests").iterdir()) == []


def test_admin_request_rejects_a_result_with_another_id(helper_root, monkeypatch) -> None:
    def forged(predicate, timeout_s, poll_s) -> None:
        request = next((helper_root / "requests").glob("*.json"))
        data = json.loads(request.read_text(encoding="utf-8"))
        reply = {"id": "0" * 32, "verb": data["verb"], "ok": True, "value": "0", "error": None}
        (helper_root / "results" / request.name).write_text(json.dumps(reply), "utf-8")

    monkeypatch.setattr(admin, "wait_for", forged)
    result = admin.request("wfp-count", "C:\\x.exe", "2026-11-13T00:00:00Z", timeout_s=5)
    assert result.ok is False


def test_admin_request_times_out_without_a_helper(helper_root) -> None:
    with pytest.raises(TimeoutError):
        admin.request("firewall-unblock-app", timeout_s=0.3, poll_s=0.05)


def s04_answers(
    count: str = "0",
    verb_ok: bool = False,
    path_ok: bool = False,
    verb_error: str = "verb-not-allowed",
    path_error: str = "path-not-allowed",
):
    def request(verb: str, *args: str, timeout_s: float = 30, **_: object) -> admin.AdminResult:
        if verb == "firewall-block-app":
            return admin.AdminResult(True, "lianiq-e2e-block-app")
        if verb == "wfp-count" and args[0].lower().endswith("cmd.exe"):
            return admin.AdminResult(
                path_ok, "0" if path_ok else None, None if path_ok else path_error
            )
        if verb == "wfp-count":
            return admin.AdminResult(True, count)
        return admin.AdminResult(verb_ok, None, None if verb_ok else verb_error)

    return request


@pytest.mark.parametrize(
    ("answers", "status"),
    [
        (s04_answers(), Status.PASS),
        (s04_answers(count="1"), Status.FAIL),
        (s04_answers(verb_ok=True), Status.FAIL),
        (s04_answers(path_ok=True), Status.FAIL),
        # A rejection for another reason is not the AC-10 allow-list rejection.
        (s04_answers(verb_error="helper-timeout"), Status.FAIL),
        (s04_answers(verb_error="malformed-request"), Status.FAIL),
        (s04_answers(path_error="argument-count"), Status.FAIL),
        (s04_answers(path_error="helper-timeout"), Status.FAIL),
    ],
)
def test_s04_passes_only_with_zero_attempts_and_both_probes_rejected(
    tmp_path, monkeypatch, repo, answers, status
) -> None:
    monkeypatch.setattr(admin, "request", answers)
    ctx = context(tmp_path, repo, "a" * 40)
    s04.begin(ctx)
    row = s04.finish(ctx)
    assert row.status is status, row.checks
    assert [c.name for c in row.checks] == [
        "block-rule-added", "unlisted-verb-rejected", "foreign-path-rejected",
        "non-loopback-attempts",
    ]  # fmt: skip


def test_wait_for_polls_a_state_and_raises_on_timeout() -> None:
    values = iter([False, False, True])
    wait_for(lambda: next(values), timeout_s=2, poll_s=0.01)
    with pytest.raises(TimeoutError):
        wait_for(lambda: False, timeout_s=0.05, poll_s=0.01)
