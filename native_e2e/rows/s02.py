"""S-02: ``python scripts/doctor.py`` passes; its redacted output is stored (contract §5)."""

from __future__ import annotations

from native_e2e import proc
from native_e2e.context import RunContext
from native_e2e.evidence.model import Row

TIMEOUT_S = 300


def run(ctx: RunContext) -> Row:
    return proc.tool_row(ctx, "S-02", ["scripts/doctor.py"], "logs/s02-doctor.txt", TIMEOUT_S)
