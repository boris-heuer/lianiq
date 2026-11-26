"""Row order of one run (CAP-0174 spec §2.2.1 step 4, §2.3; contract §5).

S-01 → S-02 → S-03 → (S-04 window opens) → S-05 → C-04 → E-01 → E-11 → E-03 → E-10
→ E-14 → E-13 → E-15 → E-27 → E-28 → E-29 → E-31 → E-32 → E-23 → E-26 → E-16 → E-18 → E-19
→ E-20 → E-21 → E-22 → E-24 → E-25 → E-30 → E-33 → C-05 → C-06 → C-09 → E-12 → C-03 → SHOT → (app left open is closed; S-04 window
closes, S-04 recorded) → E-17 → T-01 → T-02 → T-05 → T-03 → T-04 (T-05 checks the models
junction before T-03 deletes the scratch folders' parent). E-17 presses **Download** (a
blocked connection attempt), so it runs after ``s04.finish`` while the block rule still
holds (T-04 removes it); E-18 runs the E-18/E-19 scratch group and E-19 returns its row.

Rules: only a passing S-01 lets any later row run (fork commit, leftover marker). Without
an S-03 backup the app rows, UIA rows included, do not run (CAP-0168: T-01 would be
impossible); T rows still run. A row that raises is ``fail`` with the exception type only.
Rows are never retried. The T rows run even when an earlier row raised. A full run gives
every Phase 1 row a status (AC-15).
"""

from __future__ import annotations

from collections.abc import Callable

from native_e2e import uia_app
from native_e2e.context import RunContext
from native_e2e.evidence.model import Row, Status
from native_e2e.rows import (
    c03,
    c04,
    c05,
    e01,
    e03,
    e10,
    e11,
    e12,
    e13,
    e14,
    e15,
    e16,
    e17,
    e18,
    e19,
    e20,
    e23,
    e24,
    e25,
    e26,
    e27,
    e28,
    e29,
    e30,
    e31,
    e32,
    e33,
    s01,
    s02,
    s03,
    s04,
    s05,
    shot,
    teardown,
)
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
        ("E-01", e01.run),
        ("E-11", e11.run),
        ("E-03", e03.run),
        ("E-10", e10.run),
        ("E-14", e14.run),  # CAP-0170: starts and closes its own app
        ("E-13", e13.run),
        ("E-15", e15.run),
        ("E-27", e27.run),  # E-27..E-30: voice output (CAP-0167), each with its own app
        ("E-28", e28.run),
        ("E-29", e29.run),
        ("E-31", e31.run),  # E-31..E-33: keyboard rows, each with its own app
        ("E-32", e32.run),
        ("E-23", e23.run),  # CAP-0172 session rule, limit, privacy (image models)
        ("E-26", e26.run),  # CAP-0170 session rule, Stop, privacy (image models)
        ("E-16", e16.run),  # CAP-0171 offline provisioning: scratch-model groups
        ("E-18", e18.run),  # runs E-18 and E-19 on one scratch group
        ("E-19", e19.run),
        ("E-20", e20.run),  # E-20..E-22: one scratch-model group, run by e20.run
        ("E-21", e20.run_e21),
        ("E-22", e20.run_e22),
        ("E-24", e24.run),  # E-24, E-25: one scratch-model group (CAP-0170 Listen)
        ("E-25", e25.run),
        ("E-30", e30.run),  # scratch models: restores the junction itself
        ("E-33", e33.run),
        ("C-05", c05.c05),  # C-05, C-06, C-09: repository scripts
        ("C-06", c05.c06),
        ("C-09", c05.c09),
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
                try:
                    uia_app.close_open(ctx)
                except Exception:  # noqa: BLE001, S110 - the T rows and S-04 still run
                    pass
                rows["S-04"] = _guard("S-04", s04.finish, ctx)
                rows["E-17"] = _guard("E-17", e17.run, ctx)  # outside the S-04 window
    finally:
        for row in teardown.run(ctx):
            rows[row.id] = row
    return rows
