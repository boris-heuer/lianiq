"""C-05, C-06, C-09: repository scripts inside the S-04 window (spec §2.2; CAP-0174 AC-12).

Each row runs its script with the run's Python from the checkout (``proc``, as C-03 and
C-04) and passes on exit 0. ``self_test.py`` prints recognised and translated text, so each
log under ``logs/`` holds only the output's SHA-256 and the duration (``digest_only``).

- C-05 (CAP-0167 C-03) ``scripts\\self_test.py``
- C-06 (CAP-0167 C-03) ``scripts\\call_bridge_self_test.py`` (both lanes over the image models)
- C-09 (CAP-0171 C-02) ``scripts\\doctor.py``, plus the app interpreter's S-04 connection
  count for the row's window, which must be 0.

C-04 already runs ``call_bridge_self_test.py --synthetic`` and C-03 ``ui_self_test.py``.
``scripts\\download_models.py`` never runs: it always downloads and stages into ``models``
(read-only in the image), and a blocked attempt would count against S-04.
"""

from __future__ import annotations

import time

from native_e2e import proc
from native_e2e.context import RunContext
from native_e2e.evidence.model import Row, Status
from native_e2e.rows import s04
from native_e2e.rows.common import check, make_row

TIMEOUT_S = 600


def c05(ctx: RunContext) -> Row:
    log = "logs/c05-self-test.txt"
    script = ["scripts/self_test.py"]
    return proc.tool_row(ctx, "C-05", script, log, TIMEOUT_S, digest_only=True)


def c06(ctx: RunContext) -> Row:
    log = "logs/c06-call-bridge-self-test.txt"
    script = ["scripts/call_bridge_self_test.py"]
    return proc.tool_row(ctx, "C-06", script, log, TIMEOUT_S, digest_only=True)


def c09(ctx: RunContext) -> Row:
    since, started = s04.now_iso(), time.monotonic()
    result = proc.run_tool([ctx.python, "scripts/doctor.py"], ctx.repo, TIMEOUT_S)
    seconds = time.monotonic() - started
    artifact = ctx.write_log("logs/c09-doctor.txt", proc.digest_text(result, seconds))
    # A WFP event logged only after this count still reaches S-04: ``s04.finish`` counts the
    # whole window from ``s04.begin`` after the last app row.
    count = s04.count_since(ctx, since)
    detail = "unreadable" if count is None else f"count={count}"
    checks = [
        proc.tool_check("exit-code-0", result),
        check("connection-count-0", count == 0, detail),
    ]
    failed = any(item.result is not Status.PASS for item in checks)
    return make_row("C-09", checks, (artifact,), reason="tool-failed" if failed else None)
