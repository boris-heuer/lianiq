"""Unit tests of the SHOT, S-03 and teardown rows and the tool rows (CAP-0174 AC-12, AC-13).

SHOT compares the capture with the reference from ``main`` (fetched at job start): equal →
``pass``, changed → ``pending`` with ``compare/application-ui.png``, missing → ``fail``.
The capture script and the self tests are replaced by fakes; the real ones need the VM.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from native_e2e import proc, winenv
from native_e2e.context import RunContext
from native_e2e.evidence.model import Status
from native_e2e.evidence.sums import file_sha256
from native_e2e.rows import c03, s03, shot, teardown


def png(path: Path, changed: bool = False) -> Path:
    from PySide6.QtGui import QColor, QImage, QPainter

    image = QImage(200, 120, QImage.Format.Format_RGB32)
    image.fill(QColor(240, 240, 240))
    if changed:
        painter = QPainter(image)
        painter.fillRect(20, 20, 40, 40, QColor(10, 10, 10))
        painter.end()
    path.parent.mkdir(parents=True, exist_ok=True)
    assert image.save(str(path), "PNG")
    return path


@pytest.fixture
def ctx(tmp_path) -> RunContext:
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    context = RunContext(
        commit="a" * 40, out=tmp_path / "out", repo=repo, temp=tmp_path / "temp",
        image_root=tmp_path / "image",
    )  # fmt: skip
    context.temp.mkdir()
    context.out.mkdir()
    return context


def capture(changed: bool | None):
    def run_tool(args, cwd, timeout_s):
        output = Path(args[args.index("--output") + 1])
        if changed is not None:
            png(output, changed)
        return proc.ToolResult(0, "saved\n", False)

    return run_tool


@pytest.mark.parametrize(
    ("changed", "status", "sheet"),
    [(False, Status.PASS, False), (True, Status.PENDING, True), (None, Status.FAIL, False)],
)
def test_shot_compares_with_the_main_reference(ctx, monkeypatch, changed, status, sheet) -> None:
    ctx.state["reference"] = png(ctx.temp / "reference.png")
    monkeypatch.setattr(proc, "run_tool", capture(changed))
    row = shot.run(ctx)
    assert row.status is status, row.checks
    assert (ctx.out / "compare" / "application-ui.png").is_file() is sheet
    paths = [artifact.path for artifact in row.artifacts]
    if status is not Status.FAIL:
        assert paths[0] == "screens/application-ui.png"
        assert row.artifacts[0].sha256 == file_sha256(ctx.out / paths[0])
    if sheet:
        assert row.reason == "screenshot-changed-po-signoff-required"
        assert "compare/application-ui.png" in paths


def test_shot_captures_into_the_artifact_never_the_checkout(ctx, monkeypatch) -> None:
    seen: list[list[str]] = []

    def run_tool(args, cwd, timeout_s):
        seen.append(list(args))
        return capture(False)(args, cwd, timeout_s)

    ctx.state["reference"] = png(ctx.temp / "reference.png")
    monkeypatch.setattr(proc, "run_tool", run_tool)
    shot.run(ctx)
    output = Path(seen[0][seen[0].index("--output") + 1])
    assert output == ctx.out / "screens" / "application-ui.png"
    assert seen[0][1] == str(ctx.repo / "scripts" / "capture_readme_screenshot.py")


def test_shot_fails_without_a_reference(ctx, monkeypatch) -> None:
    ctx.state["reference"] = None
    monkeypatch.setattr(proc, "run_tool", capture(False))
    assert shot.run(ctx).status is Status.FAIL


def test_c03_keeps_only_the_last_20_lines_redacted(ctx, monkeypatch) -> None:
    lines = "".join(f"line {n} D:\\x\\y\n" for n in range(30))
    monkeypatch.setattr(
        proc, "run_tool", lambda args, cwd, timeout_s: proc.ToolResult(0, lines, False)
    )
    row = c03.run(ctx)
    assert row.status is Status.PASS
    log = (ctx.out / row.artifacts[0].path).read_text(encoding="utf-8").splitlines()
    assert log[0] == "line 10 <path>" and len(log) == 20
    assert proc.child_env().get("QT_QPA_PLATFORM") is None


def test_a_tool_row_fails_on_a_non_zero_exit_or_a_timeout(ctx, monkeypatch) -> None:
    monkeypatch.setattr(
        proc, "run_tool", lambda args, cwd, timeout_s: proc.ToolResult(1, "", False)
    )
    assert c03.run(ctx).status is Status.FAIL
    monkeypatch.setattr(
        proc, "run_tool", lambda args, cwd, timeout_s: proc.ToolResult(None, "", True)
    )
    assert c03.run(ctx).status is Status.FAIL


def test_run_tool_runs_a_real_child_with_a_timeout(tmp_path) -> None:
    result = proc.run_tool([sys.executable, "-c", "print('hi')"], tmp_path, 30)
    assert (result.code, result.output.strip(), result.timed_out) == (0, "hi", False)
    slow = proc.run_tool([sys.executable, "-c", "import time; time.sleep(5)"], tmp_path, 0.5)
    assert slow.timed_out and slow.code is None


@pytest.mark.parametrize("existed", [True, False])
def test_s03_backs_up_and_t01_restores_the_local_settings(ctx, monkeypatch, existed) -> None:
    settings = ctx.repo / "config" / "settings.local.json"
    if existed:
        settings.write_text('{"a": 1}', encoding="utf-8")
    row = s03.run(ctx)
    assert row.status is Status.PASS
    detail = row.checks[0].detail
    assert detail == ("sha256=" + file_sha256(settings) if existed else "absent")
    settings.write_text('{"changed": true}', encoding="utf-8")  # E-11 writes legacy settings

    monkeypatch.setattr(winenv, "cable_present", lambda: True)
    monkeypatch.setattr(winenv, "display_scale_percent", lambda: 100)
    monkeypatch.setattr(winenv, "process_running", lambda name: False)
    monkeypatch.setattr(
        teardown.admin, "request", lambda verb, *a, **k: teardown.admin.AdminResult(True, "removed")
    )
    rows = {row.id: row for row in teardown.run(ctx)}

    assert [rows[t].status for t in ("T-01", "T-02", "T-03", "T-04")] == [Status.PASS] * 4
    assert settings.is_file() is existed
    if existed:
        assert settings.read_text(encoding="utf-8") == '{"a": 1}'
    assert not ctx.temp.exists()


def test_t01_is_blocked_without_an_s03_backup_and_leaves_the_settings(ctx, monkeypatch) -> None:
    settings = ctx.repo / "config" / "settings.local.json"
    settings.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(winenv, "cable_present", lambda: True)
    monkeypatch.setattr(winenv, "display_scale_percent", lambda: 100)
    monkeypatch.setattr(winenv, "process_running", lambda name: False)
    monkeypatch.setattr(
        teardown.admin,
        "request",
        lambda verb, *a, **k: teardown.admin.AdminResult(False, None, "x"),
    )
    rows = {row.id: row for row in teardown.run(ctx)}
    assert (rows["T-01"].status, rows["T-01"].reason) == (Status.BLOCKED, "no-s03-backup")
    assert settings.is_file()
    assert rows["T-04"].status is Status.FAIL  # the firewall rule was not confirmed removed


def test_t01_fails_when_the_restored_settings_differ_from_the_s03_digest(ctx, monkeypatch) -> None:
    settings = ctx.repo / "config" / "settings.local.json"
    settings.write_text('{"a": 1}', encoding="utf-8")
    assert s03.run(ctx).status is Status.PASS
    ctx.state["settings_backup"]["path"].write_text('{"a": 2}', encoding="utf-8")  # tampered
    row = teardown.t01(ctx)
    assert (row.status, row.reason) == (Status.FAIL, "restore-failed")
