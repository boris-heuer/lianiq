"""S-04: offline proof by an outbound block rule and WFP counting (contract §5, PO 2026-11-11).

``begin`` runs before the first app row: the admin helper adds the outbound block rule for
the interpreter that runs the app (``sys._base_executable``; the venv launcher starts it),
the counting window opens, and two probes check the helper's allow-list: one unlisted verb
and one foreign path must both be rejected. ``finish`` runs after the last app row and counts
WFP events 5156/5157 of that interpreter with a non-loopback address since ``begin``. Pass
iff the rule was added, both probes were rejected and the count is 0. T-04 removes the rule.
No check detail carries a path.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from native_e2e import admin
from native_e2e.context import RunContext
from native_e2e.evidence.model import Check, Row
from native_e2e.rows.common import check, make_row

UNLISTED_VERB = "firewall-disable"
COUNT_TIMEOUT_S = 120.0


def interpreter() -> str:
    return getattr(sys, "_base_executable", None) or sys.executable


def foreign_path() -> str:
    return str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cmd.exe")


def _ask(verb: str, *args: str, timeout_s: float = admin.DEFAULT_TIMEOUT_S) -> admin.AdminResult:
    try:
        return admin.request(verb, *args, timeout_s=timeout_s)
    except TimeoutError:
        return admin.AdminResult(False, None, "helper-timeout")


def _rejected(name: str, result: admin.AdminResult, expected: str) -> Check:
    return check(name, not result.ok and result.error == expected, result.error or "accepted")


def begin(ctx: RunContext) -> None:
    since = datetime.now(UTC).isoformat(timespec="seconds")
    block = _ask("firewall-block-app", interpreter())
    checks = [
        check("block-rule-added", block.ok, block.error),
        _rejected("unlisted-verb-rejected", _ask(UNLISTED_VERB), "verb-not-allowed"),
        _rejected(
            "foreign-path-rejected", _ask("wfp-count", foreign_path(), since), "path-not-allowed"
        ),
    ]
    ctx.state["s04"] = {"since": since, "checks": checks}


def finish(ctx: RunContext) -> Row:
    state = ctx.state.get("s04")
    if state is None:
        return make_row("S-04", [check("block-rule-added", False, "not-started")], reason="not-run")
    checks = list(state["checks"])
    count = _ask("wfp-count", interpreter(), state["since"], timeout_s=COUNT_TIMEOUT_S)
    counted = count.ok and (count.value or "").isdigit()
    detail = f"count={count.value}" if counted else (count.error or "unreadable")
    checks.append(check("non-loopback-attempts", counted and count.value == "0", detail))
    return make_row("S-04", checks, reason="offline-proof-failed")
