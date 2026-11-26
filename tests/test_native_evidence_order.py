"""Phase 1 row order of the evidence model (CAP-0174 AC-01, spec §2.4).

Split from ``tests/test_native_evidence.py`` (source size limit); the runner-order test in
``tests/test_native_rows.py`` checks the same order on ``runner.execute``.
"""

from __future__ import annotations

from native_e2e.evidence.model import PHASE1_ROWS


def test_phase1_rows_follow_the_spec_order() -> None:
    assert PHASE1_ROWS == (
        "S-01", "S-02", "S-03", "S-04", "S-05", "C-04", "E-01", "E-11", "E-03", "E-10",
        "E-14", "E-13", "E-15", "E-27", "E-28", "E-29", "E-31", "E-32", "E-23", "E-26",
        "E-16", "E-18", "E-19", "E-20", "E-21", "E-22", "E-24", "E-25", "E-30", "E-33",
        "E-34", "E-35", "E-36", "E-37", "E-38", "E-39", "E-40", "C-05", "C-06", "C-09",
        "E-12", "C-03", "SHOT", "E-17", "T-01", "T-02", "T-05", "T-03", "T-04",
    )  # fmt: skip
