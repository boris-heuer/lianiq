"""S-05: display scale 100 % and Narrator not running (contract §5)."""

from __future__ import annotations

from native_e2e import winenv
from native_e2e.context import RunContext
from native_e2e.evidence.model import Row
from native_e2e.rows.common import check, make_row

NARRATOR = "Narrator.exe"


def run(ctx: RunContext) -> Row:
    scale = winenv.display_scale_percent()
    checks = [
        check("display-scale-100", scale == 100, f"{scale} %"),
        check("narrator-not-running", not winenv.process_running(NARRATOR)),
    ]
    return make_row("S-05", checks, reason="display-state")
