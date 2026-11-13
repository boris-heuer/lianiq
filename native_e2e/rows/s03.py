"""S-03: back up and hash ``config/settings.local.json`` or record ``absent`` (contract §5).

The backup goes to ``%TEMP%\\lianiq-e2e\\settings.local.backup.json`` (CAP-0168 S-03) and is
never part of the artifact: settings may name devices. T-01 restores it.
"""

from __future__ import annotations

import shutil

from native_e2e.context import RunContext
from native_e2e.evidence.model import Row
from native_e2e.evidence.sums import file_sha256
from native_e2e.rows.common import check, make_row

BACKUP_NAME = "settings.local.backup.json"


def run(ctx: RunContext) -> Row:
    source = ctx.local_settings
    backup = ctx.temp / BACKUP_NAME
    if not source.is_file():
        ctx.state["settings_backup"] = {"existed": False, "sha256": None, "path": backup}
        return make_row("S-03", [check("backup-recorded", True, "absent")])
    ctx.temp.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, backup)
    digest = file_sha256(source)
    ok = file_sha256(backup) == digest
    if ok:
        ctx.state["settings_backup"] = {"existed": True, "sha256": digest, "path": backup}
    return make_row("S-03", [check("backup-recorded", ok, f"sha256={digest}")], reason="no-backup")
