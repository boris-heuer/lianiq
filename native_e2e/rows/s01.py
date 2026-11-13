"""S-01: exact commit, branch containment, environment and the run marker (contract §5).

Order of the checks: HEAD equals ``commit``; a branch of this repository
(``refs/remotes/origin/*``, fetched with full history) contains it, otherwise the row is
``blocked`` with ``commit-not-in-repository-branch`` (the workflow already stopped such a
run before any project code, this is the in-job record); the environment values from the
live system and ``image.json`` are present; no run marker exists (otherwise ``fail`` with
``not-clean-snapshot``: the checkpoint was not reverted); then the marker is written. Only a
passing S-01 lets later rows run.
"""

from __future__ import annotations

import json
import platform
import subprocess
from datetime import UTC, datetime

from native_e2e import winenv
from native_e2e.context import RunContext
from native_e2e.evidence.model import Row
from native_e2e.rows.common import blocked_row, check, make_row

NOT_IN_BRANCH = "commit-not-in-repository-branch"
NOT_CLEAN = "not-clean-snapshot"
AUDIO = "virtual (VB-Cable A)"


def _git(ctx: RunContext, *args: str) -> tuple[int, str]:
    completed = subprocess.run(
        ["git", "-C", str(ctx.repo), *args], capture_output=True, text=True, check=False
    )
    return completed.returncode, completed.stdout


def branches_containing(ctx: RunContext) -> list[str]:
    code, out = _git(
        ctx, "for-each-ref", "--contains", ctx.commit, "--format=%(refname)", "refs/remotes/origin/"
    )
    if code != 0:
        return []
    return [ref for ref in out.split() if ref != "refs/remotes/origin/HEAD"]


def environment(ctx: RunContext) -> dict[str, str]:
    image = ctx.image()
    return {
        "windows_build": winenv.windows_build(),
        "image": str(image.get("image") or ""),
        "python": platform.python_version(),
        "models_manifest_sha256": str(image.get("models_manifest_sha256") or ""),
        "audio": AUDIO,
    }


def run(ctx: RunContext) -> Row:
    code, head = _git(ctx, "rev-parse", "HEAD")
    head_ok = code == 0 and head.strip() == ctx.commit
    contained = branches_containing(ctx)
    checks = [check("head-equals-commit", head_ok)]
    if not contained:
        return blocked_row("S-01", NOT_IN_BRANCH)
    checks.append(check("commit-in-repository-branch", True, f"{len(contained)} branch(es)"))
    if not head_ok:
        return make_row("S-01", checks, reason="head-differs-from-commit")
    try:
        values = environment(ctx)
    except (OSError, ValueError) as error:
        checks.append(check("environment-recorded", False, type(error).__name__))
        return make_row("S-01", checks, reason="environment-missing")
    ctx.state["environment"] = values
    missing = sorted(name for name, value in values.items() if not value)
    checks.append(check("environment-recorded", not missing, ", ".join(missing) or None))
    if missing:
        return make_row("S-01", checks, reason="environment-missing")
    if ctx.marker.exists():
        checks.append(check("run-marker-absent", False))
        return make_row("S-01", checks, reason=NOT_CLEAN)
    checks.append(check("run-marker-absent", True))
    marker = {
        "commit": ctx.commit,
        "workflow_run": ctx.workflow_run,
        "utc": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    ctx.marker.parent.mkdir(parents=True, exist_ok=True)
    ctx.marker.write_text(json.dumps(marker) + "\n", encoding="utf-8")
    checks.append(check("run-marker-written", ctx.marker.is_file()))
    return make_row("S-01", checks, reason="marker-not-written")
