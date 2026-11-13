"""C-04: ``python scripts/call_bridge_self_test.py --synthetic`` exits 0 (contract §5)."""

from __future__ import annotations

from native_e2e import proc
from native_e2e.context import RunContext
from native_e2e.evidence.model import Row

TIMEOUT_S = 600


def run(ctx: RunContext) -> Row:
    script = ["scripts/call_bridge_self_test.py", "--synthetic"]
    return proc.tool_row(ctx, "C-04", script, "logs/c04-call-bridge-self-test.txt", TIMEOUT_S)
