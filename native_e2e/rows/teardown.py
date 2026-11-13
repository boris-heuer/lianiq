"""T-01..T-04: in-job cleanup after the app rows (contract §5; CAP-0168 T rows).

- T-01 restores ``config/settings.local.json`` from the S-03 backup, or deletes it when none
  existed; without an S-03 record it is ``blocked`` and leaves the file alone.
- T-02 confirms the device state: the job only uses the virtual cable, whose two endpoints
  must still exist (no name is stored).
- T-03 deletes ``%TEMP%\\lianiq-e2e`` after resetting its ACLs (E-10 denies writes on ``ro``).
- T-04 removes the S-04 block rule through the admin helper ("reconnect the network") and
  confirms display scale 100 % and no Narrator.

After the upload the host reverts the checkpoint; the next run's S-01 marker check proves it.
"""

from __future__ import annotations

import shutil
import subprocess

from native_e2e import admin, winenv
from native_e2e.context import RunContext
from native_e2e.evidence.model import Row
from native_e2e.evidence.sums import file_sha256
from native_e2e.rows.common import blocked_row, check, error_row, make_row
from native_e2e.rows.s05 import NARRATOR


def t01(ctx: RunContext) -> Row:
    record = ctx.state.get("settings_backup")
    if record is None:
        return blocked_row("T-01", "no-s03-backup")
    target = ctx.local_settings
    if record["existed"]:
        shutil.copy2(record["path"], target)
        ok = target.is_file() and file_sha256(target) == record["sha256"]
        return make_row("T-01", [check("settings-restored", ok)], reason="restore-failed")
    target.unlink(missing_ok=True)
    return make_row("T-01", [check("settings-absent", not target.exists())], reason="delete-failed")


def t02(ctx: RunContext) -> Row:
    return make_row(
        "T-02", [check("virtual-cable-present", winenv.cable_present())], reason="device"
    )


def t03(ctx: RunContext) -> Row:
    if ctx.temp.exists():
        try:
            subprocess.run(
                ["icacls", str(ctx.temp), "/reset", "/T", "/C", "/Q"],
                capture_output=True,
                check=False,
            )
        except OSError:
            pass  # no icacls: nothing to reset, the delete below decides
        shutil.rmtree(ctx.temp, ignore_errors=True)
    return make_row(
        "T-03", [check("temp-folder-absent", not ctx.temp.exists())], reason="left-over"
    )


def t04(ctx: RunContext) -> Row:
    try:
        result = admin.request("firewall-unblock-app")
    except TimeoutError:
        result = admin.AdminResult(False, None, "helper-timeout")
    removed = result.ok and result.value in {"removed", "absent"}
    scale = winenv.display_scale_percent()
    checks = [
        check("block-rule-removed", removed, result.value or result.error),
        check("display-scale-100", scale == 100, f"{scale} %"),
        check("narrator-not-running", not winenv.process_running(NARRATOR)),
    ]
    return make_row("T-04", checks, reason="cleanup-failed")


STEPS = (("T-01", t01), ("T-02", t02), ("T-03", t03), ("T-04", t04))


def run(ctx: RunContext) -> list[Row]:
    """Run every T row; one raising row never stops the others."""
    rows = []
    for row_id, step in STEPS:
        try:
            rows.append(step(ctx))
        except Exception as error:  # noqa: BLE001 - recorded as a failed T row
            rows.append(error_row(row_id, error))
    return rows
