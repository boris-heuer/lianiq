"""SHOT: README screenshot against the accepted image on ``main`` (contract §5, N-03, N-04).

``fetch_reference`` runs at job start: ``docs/assets/application-ui.png`` from
``origin/main`` (never the checkout's copy) goes to the job temp folder. ``run`` captures
with ``scripts/capture_readme_screenshot.py --output <artifact>/screens/application-ui.png``
(the sanitized window: generic devices, no transcript) and compares with windowed SSIM:
at or above 0.990 → ``pass``; below → ``pending`` with ``compare/application-ui.png`` until
the PO signs off; a missing or unreadable image → ``fail``.
"""

from __future__ import annotations

import subprocess

from native_e2e import proc
from native_e2e.context import RunContext
from native_e2e.evidence.model import Check, Row, Status
from native_e2e.rows.common import check, make_row
from native_e2e.ssim import THRESHOLD, comparison_sheet, ssim

REFERENCE = "origin/main:docs/assets/application-ui.png"
SCREEN = "screens/application-ui.png"
SHEET = "compare/application-ui.png"
CHANGED = "screenshot-changed-po-signoff-required"
TIMEOUT_S = 300


def fetch_reference(ctx: RunContext) -> None:
    completed = subprocess.run(
        ["git", "-C", str(ctx.repo), "show", REFERENCE], capture_output=True, check=False
    )
    target = ctx.temp / "reference-application-ui.png"
    if completed.returncode != 0 or not completed.stdout:
        ctx.state["reference"] = None
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(completed.stdout)
    ctx.state["reference"] = target


def run(ctx: RunContext) -> Row:
    output = ctx.out / SCREEN
    output.parent.mkdir(parents=True, exist_ok=True)
    script = str(ctx.repo / "scripts" / "capture_readme_screenshot.py")
    result = proc.run_tool([ctx.python, script, "--output", str(output)], ctx.repo, TIMEOUT_S)
    checks = [proc.tool_check("capture-exit-code-0", result)]
    reference = ctx.state.get("reference")
    checks.append(check("reference-from-main", reference is not None and reference.is_file()))
    if not output.is_file():
        checks.append(check("screenshot-readable", False, "missing"))
        return make_row("SHOT", checks, reason="screenshot-missing")
    artifacts = [ctx.artifact(SCREEN)]
    if checks[-1].result is not Status.PASS:
        return make_row("SHOT", checks, artifacts, reason="reference-missing")
    try:
        score = ssim(reference, output)
    except ValueError:
        checks.append(check("screenshot-readable", False, "unreadable"))
        return make_row("SHOT", checks, artifacts, reason="screenshot-unreadable")
    checks.append(check("screenshot-readable", True))
    detail = f"ssim={score:.4f} threshold={THRESHOLD}"
    if score >= THRESHOLD:
        checks.append(check("ssim-at-threshold", True, detail))
        return make_row("SHOT", checks, artifacts)
    comparison_sheet(reference, output, ctx.out / SHEET)
    artifacts.append(ctx.artifact(SHEET))
    checks.append(Check("ssim-at-threshold", Status.PENDING, detail))
    return make_row("SHOT", checks, artifacts, reason=CHANGED)
