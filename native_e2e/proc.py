"""Run a repository tool as a child process for a row (CAP-0174 contract §5).

``run_tool`` runs one command with a timeout and returns its exit code and combined output;
it never retries. ``child_env`` drops ``QT_QPA_PLATFORM`` so the child uses the real window.
``tool_row`` is the shared shape of S-02, C-03 and C-04: exit 0 passes, the redacted output
(or its last lines) is stored under ``logs/``.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from native_e2e.evidence.model import Check, Status
from native_e2e.rows.common import check, make_row

if TYPE_CHECKING:
    from native_e2e.context import RunContext
    from native_e2e.evidence.model import Row


@dataclass(frozen=True)
class ToolResult:
    code: int | None  # None after a timeout
    output: str
    timed_out: bool


def child_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key != "QT_QPA_PLATFORM"}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_tool(args: Sequence[str], cwd: Path, timeout_s: float) -> ToolResult:
    try:
        completed = subprocess.run(
            list(args),
            cwd=cwd,
            env=child_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as expired:
        output = expired.output or b""
        return ToolResult(None, output.decode("utf-8", errors="replace"), True)
    return ToolResult(
        completed.returncode, completed.stdout.decode("utf-8", errors="replace"), False
    )


def tool_check(name: str, result: ToolResult) -> Check:
    detail = "timeout" if result.timed_out else f"exit {result.code}"
    return check(name, result.code == 0, detail)


def tool_row(
    ctx: RunContext,
    row_id: str,
    script: Sequence[str],
    log: str,
    timeout_s: float,
    tail: int | None = None,
) -> Row:
    """Run ``python <script...>`` from the checkout; pass iff it exits 0."""
    result = run_tool([ctx.python, *script], ctx.repo, timeout_s)
    lines = result.output.splitlines()
    if tail is not None:
        lines = lines[-tail:]
    artifact = ctx.write_log(log, "\n".join(lines) + "\n")
    passed = tool_check("exit-code-0", result)
    reason = None if passed.result is Status.PASS else "tool-failed"
    return make_row(row_id, (passed,), (artifact,), reason=reason)
