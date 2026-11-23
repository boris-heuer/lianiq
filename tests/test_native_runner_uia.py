"""The runner gates the UIA rows E-01, E-11, E-03, E-10 and E-15 as before (CAP-0174 AC-15).

The rows run after C-04 in the S-04 window only when S-01 passed and S-03 recorded the
settings backup; an app a UIA row left open is closed before S-04 is recorded and the T rows
run. The row fakes come from ``test_native_rows``.
"""

from __future__ import annotations

import pytest

from native_e2e import runner
from native_e2e.evidence.model import Check, Row, Status
from tests.test_native_rows import context, install


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"  # every row is faked: no git history is needed
    path.mkdir()
    return path


@pytest.mark.parametrize("status", [Status.BLOCKED, Status.FAIL])
def test_without_an_s03_backup_no_app_row_runs_but_teardown_does(
    tmp_path, monkeypatch, repo, status
) -> None:
    calls: list[str] = []
    install(monkeypatch, calls, s03_status=status)
    rows = runner.execute(context(tmp_path, repo, "a" * 40))
    assert calls == ["S-01", "S-02", "S-03", "T-01", "T-02", "T-03", "T-04"]
    assert not {"E-01", "E-11", "E-03", "E-10", "E-15"} & set(rows)


def test_an_app_left_open_is_closed_even_when_a_uia_row_raises(tmp_path, monkeypatch, repo) -> None:
    from native_e2e.rows import e03

    calls: list[str] = []
    install(monkeypatch, calls)

    def boom(ctx) -> Row:
        raise TimeoutError("window")

    monkeypatch.setattr(e03, "run", boom)
    rows = runner.execute(context(tmp_path, repo, "a" * 40))
    assert rows["E-03"].checks == (Check("unexpected-error", Status.FAIL, "TimeoutError"),)
    assert calls.index("app closed") < calls.index("S-04") < calls.index("T-01")
