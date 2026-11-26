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
    "E-01": ("AC-11",),
    "E-11": ("AC-11",),
    "E-03": ("AC-11",),
    "E-10": ("AC-11",),
    "E-14": ("AC-31",),  # CAP-0170 AC-31 (Listen & translate); the others are CAP-0174 ACs
    "E-13": ("AC-37",),  # CAP-0172 Text translation (its spec §5)
    "E-15": ("AC-25",),  # CAP-0167 AC-25: spoken output (the receipt names the capability)
    "E-27": ("AC-01", "AC-02", "AC-12", "AC-29"),  # E-27..E-30: CAP-0167 (its spec §5)
    "E-28": ("AC-07", "AC-08", "AC-11", "AC-14", "AC-15"),
    "E-29": ("AC-10", "AC-13"),
    "E-31": ("AC-28", "AC-22"),  # CAP-0168 AC-28, CAP-0167 AC-22 (keyboard)
    "E-32": ("AC-30", "AC-19", "AC-36"),  # CAP-0170 AC-30, CAP-0172 AC-19 and AC-36
    "E-33": ("AC-26",),  # CAP-0171 AC-26
    "E-30": ("AC-03", "AC-04", "AC-20", "AC-29"),
    "E-26": ("AC-10", "AC-12", "AC-13", "AC-19", "AC-21", "AC-27", "AC-32"),  # CAP-0170 ACs
    "E-24": ("AC-25",),
    "E-25": ("AC-03", "AC-04", "AC-06", "AC-07", "AC-08", "AC-16", "AC-21", "AC-26"),
    "E-23": ("AC-12", "AC-21", "AC-26", "AC-27", "AC-33"),  # E-20..E-23: CAP-0172 ACs
    "E-20": ("AC-31", "AC-32"),
    "E-21": ("AC-07", "AC-28"),
    "E-22": ("AC-05", "AC-16", "AC-22", "AC-23", "AC-25", "AC-30", "AC-38"),
    # CAP-0171 (offline language provisioning) ACs named in its e2e plan rows E-01..E-09
    "E-16": ("AC-01", "AC-03", "AC-04", "AC-05", "AC-06", "AC-22", "AC-29"),  # E-01, E-02, E-06
    "E-17": ("AC-13", "AC-21", "AC-28"),  # E-07
    "E-18": ("AC-10", "AC-11", "AC-15", "AC-16"),  # E-08, E-05
    "E-19": ("AC-18", "AC-20", "AC-21", "AC-28"),  # E-09, E-04
    "C-05": ("AC-12",),  # C-05, C-06, C-09: code rows of the automated PO rows (spec §2.2)
    "C-06": ("AC-12",),
    "C-09": ("AC-12",),
    "E-12": ("AC-12",),
    "C-03": ("AC-12",),
    "SHOT": ("AC-13",),
    "T-01": ("AC-08",),
    "T-02": ("AC-08",),
    "T-03": ("AC-08",),
    "T-04": ("AC-08",),
    "T-05": ("AC-08",),
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
