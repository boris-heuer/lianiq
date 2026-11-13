"""Row building blocks shared by every row module (CAP-0174 contract §5, §7.1).

A row's status follows from its checks: any ``fail`` → ``fail``, else any ``blocked`` →
``blocked``, else any ``pending`` → ``pending``, else ``pass``. ``ROW_ACS`` names the
acceptance criteria each row's evidence serves (spec §5).
"""

from __future__ import annotations

from collections.abc import Iterable

from native_e2e.evidence.model import Artifact, Check, Method, Row, Status

ROW_ACS: dict[str, tuple[str, ...]] = {
    "S-01": ("AC-09", "AC-10", "AC-16"),
    "S-02": ("AC-10",),
    "S-03": ("AC-10",),
    "S-04": ("AC-10",),
    "S-05": ("AC-10",),
    "C-04": ("AC-12",),
    "E-12": ("AC-12",),
    "C-03": ("AC-12",),
    "SHOT": ("AC-13",),
    "T-01": ("AC-08",),
    "T-02": ("AC-08",),
    "T-03": ("AC-08",),
    "T-04": ("AC-08",),
}


def check(name: str, ok: bool, detail: str | None = None) -> Check:
    return Check(name, Status.PASS if ok else Status.FAIL, detail)


def status_of(checks: Iterable[Check]) -> Status:
    results = {item.result for item in checks}
    for status in (Status.FAIL, Status.BLOCKED, Status.PENDING):
        if status in results:
            return status
    return Status.PASS if results else Status.FAIL


def make_row(
    row_id: str,
    checks: Iterable[Check],
    artifacts: Iterable[Artifact] = (),
    reason: str | None = None,
    method: Method = Method.NATIVE,
) -> Row:
    checks = tuple(checks)
    status = status_of(checks)
    return Row(
        row_id,
        ROW_ACS.get(row_id, ()),
        method,
        status,
        checks,
        tuple(artifacts),
        reason if status is not Status.PASS else None,
    )


def error_row(row_id: str, error: BaseException) -> Row:
    """A row whose code raised: ``fail`` with the exception type only (never its message)."""
    return make_row(
        row_id,
        (Check("unexpected-error", Status.FAIL, type(error).__name__),),
        reason="unexpected-error",
    )


def blocked_row(row_id: str, reason: str, detail: str | None = None) -> Row:
    return make_row(row_id, (Check(reason, Status.BLOCKED, detail),), reason=reason)
