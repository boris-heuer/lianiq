"""Unit tests of the native row runner CLI (CAP-0174 contract §3; AC-13, AC-14, AC-15 halves).

The rows themselves need the VM; here ``runner.prepare`` and ``runner.execute`` are replaced
by fakes, so the tests pin what ``run`` does with the rows: receipt, ``junit.xml``,
``SHA256SUMS``, redaction scan, canary, job summary and exit code, and what ``verify``
accepts as the upload gate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from native_e2e import __main__ as cli
from native_e2e import runner
from native_e2e.evidence.model import PHASE1_ROWS, Check, Method, Row, Status, validate
from native_e2e.evidence.redaction import scan
from native_e2e.evidence.sums import SUMS_NAME, write_sums
from native_e2e.scrub import scrub

COMMIT = "0123456789abcdef0123456789abcdef01234567"
UIA_ROWS = ("E-01", "E-11", "E-03", "E-10")
ENVIRONMENT = {
    "windows_build": "26100.4349",
    "image": "win11-native-e2e@20261113",
    "python": "3.12.10",
    "models_manifest_sha256": "a" * 64,
    "audio": "virtual (VB-Cable A)",
}


def make_row(row_id: str, status: Status = Status.PASS, reason: str | None = None) -> Row:
    return Row(row_id, ("AC-12",), Method.NATIVE, status, (Check("probe", status),), (), reason)


def fake_rows(monkeypatch, statuses=None, ids=None, write=None) -> None:
    statuses = statuses or {}
    ids = ids if ids is not None else [r for r in PHASE1_ROWS if r not in UIA_ROWS]

    def execute(ctx):
        ctx.state["environment"] = dict(ENVIRONMENT)
        if write:
            write(ctx)
        return {r: make_row(r, *statuses.get(r, (Status.PASS,))) for r in ids}

    monkeypatch.setattr(runner, "prepare", lambda ctx: None)
    monkeypatch.setattr(runner, "execute", execute)


@pytest.fixture
def summary(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(path))
    monkeypatch.setenv("GITHUB_RUN_ID", "4242")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    return path


def run(out: Path, *extra: str) -> int:
    return cli.main(["run", "--commit", COMMIT, "--out", str(out), *extra])


def receipt(out: Path) -> dict:
    return json.loads((out / "native-evidence.json").read_text(encoding="utf-8"))


def test_run_writes_receipt_junit_sums_and_the_row_table(tmp_path, monkeypatch, summary) -> None:
    fake_rows(monkeypatch)
    out = tmp_path / "evidence"

    code = run(out, "--capability", "CAP-0174", "--work-item", "WI-03")

    data = receipt(out)
    assert validate(data) == [f"open: {row_id}" for row_id in UIA_ROWS]
    assert data["commit"] == COMMIT and data["workflow_run"] == "4242-1"
    assert (data["capability"], data["work_item"]) == ("CAP-0174", "WI-03")
    assert [row["id"] for row in data["rows"]] == [r for r in PHASE1_ROWS if r not in UIA_ROWS]
    assert data["redaction_scan"]["status"] == "clean"
    assert data["redaction_scan"]["files_scanned"] >= 1
    assert (out / "junit.xml").is_file() and (out / SUMS_NAME).is_file()
    assert code == 1  # open rows are neither pass nor pending
    table = summary.read_text(encoding="utf-8")
    for row_id in PHASE1_ROWS:
        assert f"| {row_id} |" in table
    assert "| E-01 | - | open |" in table
    assert cli.main(["verify", str(out)]) == 0


def test_run_exits_0_only_when_every_phase1_row_is_pass_or_pending(
    tmp_path, monkeypatch, summary
) -> None:
    fake_rows(monkeypatch, {"SHOT": (Status.PENDING, "screenshot-changed")}, ids=PHASE1_ROWS)
    assert run(tmp_path / "ok") == 0
    assert "the PO must sign off `compare/application-ui.png`" in summary.read_text("utf-8")


@pytest.mark.parametrize("status", [Status.FAIL, Status.BLOCKED])
def test_a_failed_or_blocked_row_makes_the_run_red(tmp_path, monkeypatch, summary, status) -> None:
    fake_rows(monkeypatch, {"C-04": (status, "exit-code")}, ids=PHASE1_ROWS)
    assert run(tmp_path / "red") == 1
    assert cli.main(["verify", str(tmp_path / "red")]) == 0  # still uploaded


def test_the_canary_fails_the_run_and_the_gate_and_is_never_printed(
    tmp_path, monkeypatch, summary, capsys
) -> None:
    fake_rows(monkeypatch, ids=PHASE1_ROWS)
    out = tmp_path / "canary"

    assert run(out, "--plant-redaction-canary") == 2

    data = receipt(out)
    assert data["redaction_scan"]["status"] == "findings"
    assert data["redaction_scan"]["pattern_classes"] == ["secret"]
    canary = (out / "logs" / "redaction-canary.txt").read_text(encoding="utf-8").strip()
    table = summary.read_text(encoding="utf-8")
    assert "`logs/redaction-canary.txt`: secret" in table
    assert cli.main(["verify", str(out)]) == 1
    printed = capsys.readouterr()
    assert canary not in printed.out + printed.err + summary.read_text(encoding="utf-8")


def test_an_unredacted_log_fails_the_run_and_the_gate(tmp_path, monkeypatch, summary) -> None:
    def leak(ctx) -> None:
        (ctx.out / "logs").mkdir(parents=True, exist_ok=True)
        (ctx.out / "logs" / "doctor.txt").write_text("model at D:\\models\\x\n", "utf-8")

    fake_rows(monkeypatch, ids=PHASE1_ROWS, write=leak)
    out = tmp_path / "leak"
    assert run(out) == 2
    assert "`logs/doctor.txt`: drive-path" in summary.read_text(encoding="utf-8")
    assert cli.main(["verify", str(out)]) == 1


def test_verify_rejects_a_changed_file_and_a_schema_error(tmp_path, monkeypatch, summary) -> None:
    fake_rows(monkeypatch, ids=PHASE1_ROWS)
    out = tmp_path / "artifact"
    assert run(out) == 0
    (out / "junit.xml").write_text("<testsuite/>", encoding="utf-8")
    assert cli.main(["verify", str(out)]) == 1

    other = tmp_path / "schema"
    assert run(other) == 0
    data = receipt(other)
    data["commit"] = "not-a-sha"
    (other / "native-evidence.json").write_text(json.dumps(data), encoding="utf-8")
    assert cli.main(["verify", str(other)]) == 1


def test_verify_rescans_even_when_the_sums_were_rewritten(tmp_path, monkeypatch, summary) -> None:
    fake_rows(monkeypatch, ids=PHASE1_ROWS)
    out = tmp_path / "artifact"
    assert run(out) == 0
    (out / "logs").mkdir(exist_ok=True)
    # A changed artifact with consistent sums: only the re-scan can catch it.
    (out / "logs" / "late.txt").write_text("endpoint {0.0.1.00000000}.{x}\n", "utf-8")
    write_sums(out)
    assert cli.main(["verify", str(out)]) == 1


def test_run_refuses_a_bad_commit_or_a_used_output_folder(tmp_path, monkeypatch, summary) -> None:
    fake_rows(monkeypatch)
    assert cli.main(["run", "--commit", "abc", "--out", str(tmp_path / "x")]) == 3
    used = tmp_path / "used"
    used.mkdir()
    (used / "old.txt").write_text("x", encoding="utf-8")
    assert run(used) == 3


def test_scrub_leaves_nothing_the_scan_finds(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("USERNAME", "e2e")
    monkeypatch.setenv("USERPROFILE", "C:\\Users\\e2e")
    raw = (
        "user e2e in C:\\Users\\e2e\\AppData\\x.log, D:/data/models, "
        "endpoint {0.0.1.00000000}.{abc} on CABLE Output (VB-Audio) said Guten Morgen\n"
        "native-e2e and win11-native-e2e@1 stay\n"
    )
    cleaned = scrub(raw, ["CABLE Output", "guten morgen"])
    path = tmp_path / "log.txt"
    path.write_text(cleaned, encoding="utf-8")
    assert scan([path], ["CABLE Output", "guten morgen"]) == []
    assert "native-e2e and win11-native-e2e@1 stay" in cleaned
    assert "<path>" in cleaned and "<endpoint-id>" in cleaned and "<redacted>" in cleaned
