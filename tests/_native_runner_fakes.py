"""Stand-ins for the E rows in the runner-order test (``tests/test_native_rows.py``).

Each row's step is replaced by ``fake(row_id, calls)``, which records the call; E-12 is
replaced in the test itself (it runs after the C rows). The E-20..E-22 group has three steps;
E-17 runs after S-04 is recorded.
"""

from __future__ import annotations


def fake_e_rows(monkeypatch, fake, calls: list[str]) -> None:
    from native_e2e.rows import (
        e01,
        e03,
        e10,
        e11,
        e13,
        e14,
        e15,
        e16,
        e17,
        e18,
        e19,
        e20,
        e23,
        e27,
        e28,
        e29,
        e30,
    )

    singles = (e01, e11, e03, e10, e14, e13, e15, e16, e17, e18, e19, e27, e28, e29, e30, e23)
    for module, attr, row_id in (
        *((m, "run", f"E-{m.__name__[-2:]}") for m in singles),
        (e20, "run", "E-20"),
        (e20, "run_e21", "E-21"),
        (e20, "run_e22", "E-22"),
    ):
        monkeypatch.setattr(module, attr, fake(row_id, calls))
