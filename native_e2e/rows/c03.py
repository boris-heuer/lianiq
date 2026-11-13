"""C-03: ``python scripts/ui_self_test.py`` in the real window exits 0 (contract §5).

Only the last 20 output lines are stored, redacted.
"""

from __future__ import annotations

from native_e2e import proc
from native_e2e.context import RunContext
from native_e2e.evidence.model import Row

TIMEOUT_S = 900
TAIL = 20


def run(ctx: RunContext) -> Row:
    log = "logs/c03-ui-self-test.txt"
    return proc.tool_row(ctx, "C-03", ["scripts/ui_self_test.py"], log, TIMEOUT_S, tail=TAIL)
