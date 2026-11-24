"""E-17: a download attempt without a connection (CAP-0171 e2e plan E-07; spec §2.1.9).

Runs after ``s04.finish`` and before T-01, while the S-04 block rule is still active: S-04
counts every connection event of the app interpreter, blocked ones included, so the one
attempt this row provokes must fall outside its window. Scratch models ``e17`` (empty); the
app starts with ``--no-setup-assistant``. Language packs must list every catalog pack
(``provisioning.catalog_ids``; the count follows the catalog) *Downloadable* and show the empty hint ("New here? Run the setup assistant."). On
``PACK_ID`` **Get…** › tick the licence; the connection count since just before the launch
must be 0 before **Download** is pressed; then the row must show "Download unavailable: no
connection to {host}. Import the pack from a file or folder instead." with **Import…** and
**Retry**. The count after the click is recorded (the blocked attempts), never judged. One
masked screenshot. ``settings_reset`` and ``scratch_models`` restore the baseline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from native_e2e import models_swap, packs_import, uia_app
from native_e2e.evidence.model import Check, Row, Status
from native_e2e.rows import provisioning, s04, ui
from native_e2e.rows.common import blocked_row, check, make_row

if TYPE_CHECKING:
    from native_e2e.context import RunContext

PACK_ID = "mt-de-zh-hans"
SCREEN = "screens/e17-download-unavailable.png"


def _packs_shown(app: Any, s: Any, checks: list[Check]) -> bool:
    if not ui.select(app, s.NAV_LANGUAGE_PACKS, s.NAV_REGION):
        checks.append(check("all-downloadable", False, "packs-page-not-shown"))
        return False
    models = [packs_import.pack(pack_id).model for pack_id in provisioning.catalog_ids()]

    def downloadable() -> bool:
        found = provisioning.states(app.nodes(), models)
        return bool(found) and all(x == s.PACK_STATE_DOWNLOADABLE for x in found)

    if not ui.waited(checks, "all-downloadable", downloadable):
        return False
    checks[-1] = check("all-downloadable", True, f"count={len(models)}")
    checks.append(check("empty-hint-shown", ui.shows(app.nodes(), s.PACK_EMPTY_HINT)))
    return True


def _download(ctx: RunContext, app: Any, since: str, checks: list[Check], artifacts: list) -> None:
    s = ui.strings()
    if not _packs_shown(app, s, checks):
        return
    definition = packs_import.pack(PACK_ID)
    reason = packs_import._open_details(app, s, definition.model) or packs_import._accept_licence(
        app, s, definition
    )
    if reason is not None:
        checks.append(check("licence-accepted", False, reason))
        return
    checks.append(check("licence-accepted", True))
    count = s04.count_since(ctx, since)
    checks.append(check("no-connection-before-download", count == 0, f"count={count}"))
    button = ui.find(app.window_nodes(definition.model) or (), s.PACK_DOWNLOAD, "Button")
    if button is None or not button.enabled:
        checks.append(check("download-unavailable-shown", False, "download-not-enabled"))
        return
    app.press(button)
    probe = lambda: provisioning.filled(app.nodes(), s.PACK_DOWNLOAD_UNAVAILABLE, "host")
    if not ui.waited(checks, "download-unavailable-shown", probe, ui.MODEL_TIMEOUT_S):
        return
    nodes = app.nodes()
    offered = all(
        packs_import._row_button(nodes, definition.model, (label,)) is not None
        for label in (s.PACK_IMPORT, s.PACK_RETRY)
    )
    checks.append(check("import-and-retry-offered", offered))
    after = s04.count_since(ctx, since)
    checks.append(check("attempts-after-download-recorded", after is not None, f"count={after}"))
    shot, artifact = provisioning.shot(ctx, app, SCREEN, "screenshot-masked")
    checks.append(shot)
    artifacts.append(artifact)


def _block_rule_active(ctx: RunContext) -> bool:
    state = ctx.state.get("s04") or {}
    rule = [c for c in state.get("checks", ()) if c.name == "block-rule-added"]
    return bool(rule) and rule[0].result is Status.PASS


def run(ctx: RunContext) -> Row:
    if not _block_rule_active(ctx):
        return blocked_row("E-17", "s04-block-rule-missing")
    checks: list[Check] = []
    artifacts: list = []
    uia_app.close_open(ctx)
    try:
        with models_swap.scratch_models(ctx, "e17"):
            since = s04.now_iso()
            app = uia_app.launch(ctx)
            try:
                _download(ctx, app, since, checks, artifacts)
            finally:
                app.close()
    finally:
        checks.append(check("settings-baseline-restored", uia_app.settings_reset(ctx)))
    return make_row("E-17", checks, artifacts, reason="download-unavailable")
