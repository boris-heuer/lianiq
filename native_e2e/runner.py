"""Row order of one run (CAP-0174 spec §2.2.1 step 4, §2.3; contract §5).

S-01 → S-02 → S-03 → (S-04 window opens) → S-05 → C-04 → [E-01 → E-11 → E-03 → E-10, WI-04]
→ E-12 → C-03 → SHOT → (S-04 window closes, S-04 recorded) → T-01..T-04.

Rules: only a passing S-01 lets any later row run (fork commit, leftover marker). Without
an S-03 backup the app rows do not run (CAP-0168: T-01 would be impossible); T rows still
run. A row that raises is ``fail`` with the exception type only. Rows are never retried.
The T rows run even when an earlier row raised. The UIA rows of WI-04 are not run yet, so
the receipt reports them as open.
"""

from __future__ import annotations

from collections.abc import Callable

from native_e2e.context import RunContext
from native_e2e.evidence.model import Row, Status
from native_e2e.rows import c03, c04, e12, s01, s02, s03, s04, s05, shot, teardown
from native_e2e.rows.common import error_row


def prepare(ctx: RunContext) -> None:
    """Job start: create the folders and fetch the SHOT reference from ``main``."""
    ctx.out.mkdir(parents=True, exist_ok=True)
    ctx.temp.mkdir(parents=True, exist_ok=True)
    shot.fetch_reference(ctx)


def _guard(row_id: str, step: Callable[[RunContext], Row], ctx: RunContext) -> Row:
    try:
        return step(ctx)
    except Exception as error:  # noqa: BLE001 - recorded as a failed row, never retried
        return error_row(row_id, error)


def _app_rows() -> tuple[tuple[str, Callable[[RunContext], Row]], ...]:
    # Looked up at call time so each row module's ``run`` is the current one.
    return (
        ("S-05", s05.run),
        ("C-04", c04.run),
        ("E-12", e12.run),
        ("C-03", c03.run),
        ("SHOT", shot.run),
    )


def execute(ctx: RunContext) -> dict[str, Row]:
    rows: dict[str, Row] = {"S-01": _guard("S-01", s01.run, ctx)}
    if rows["S-01"].status is not Status.PASS:
        return rows
    try:
        rows["S-02"] = _guard("S-02", s02.run, ctx)
        rows["S-03"] = _guard("S-03", s03.run, ctx)
        if rows["S-03"].status is Status.PASS:
            try:
                try:
                    s04.begin(ctx)
                except Exception:  # noqa: BLE001 - S-04 then fails with "not-started"
                    ctx.state.pop("s04", None)
                for row_id, step in _app_rows():
                    rows[row_id] = _guard(row_id, step, ctx)
            finally:
                rows["S-04"] = _guard("S-04", s04.finish, ctx)
    finally:
        for row in teardown.run(ctx):
            rows[row.id] = row
    return rows
