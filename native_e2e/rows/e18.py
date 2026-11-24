"""E-18 (with E-19): import packs offline, session protection (CAP-0171 e2e plan E-08, E-05).

One scratch-model group ``e18`` for E-18 and E-19; ``run`` executes both and leaves the E-19
row in ``ctx.state["e19_row"]`` for ``e19.run``. The image folder of every German–Mandarin
pack (``provisioning.pair_ids``; packs of other pairs such as english-mandarin-pair are left
out and stay *Downloadable*) needs ``lianiq-pack.json`` (else both rows are ``blocked`` with
``image-packs-without-pack-file``, before any app starts). The app starts with ``--no-setup-assistant`` on the empty models.

E-18: a corrupt copy of ``mt-de-zh-hans`` (``packs_import.make_corrupt_copy``, under
``ctx.temp``) is imported and must be refused with "This pack cannot be imported: file
<path> failed the integrity check", the row staying *Downloadable*. Then the pair's image
pack folders are imported, each to *Validated*; the scratch ``model-manifest.json`` must
record ``source: import`` for each of them (only the record count is stored). Settings › Microphone
"CABLE Output"; Conversation **Start** (F8); Language packs › the recognition pack's
**Remove** › **Yes** must be refused with "Stop the running Conversation session first" and
leave it *Validated*; F9; **Remove** › **Yes** again ends *Downloadable*; the re-import ends
*Validated*. One masked screenshot after the imports. Then E-19 runs on the same app
(``e19.session``). The app is closed; ``scratch_models`` restores the junction and
``settings_reset`` the S-03 baseline, also when a step raises.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from native_e2e import models_swap, packs_import, uia_app
from native_e2e.evidence.model import Check, Row
from native_e2e.rows import e03, e19, provisioning, ui
from native_e2e.rows.common import blocked_row, check, error_row, make_row

if TYPE_CHECKING:
    from native_e2e.context import RunContext

GROUP = "e18"
RECOGNITION = "stt-faster-whisper-small"  # removed while Conversation runs, then re-imported
MANIFEST = "model-manifest.json"  # in the models folder (lianiq/packs/manifest.py)
SCREEN = "screens/e18-imported.png"


def manifest_sources(folder: Path) -> dict[str, str]:
    """``id`` → ``source`` of the manifest's ``packs[]`` records ({} when unreadable)."""
    try:
        data = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    records = data.get("packs") if isinstance(data, dict) else None
    return {
        str(item.get("id")): str(item.get("source"))
        for item in records or ()
        if isinstance(item, dict)
    }


def _corrupt(ctx: RunContext, app: Any, s: Any, source: Path, checks: list[Check]) -> bool:
    from lianiq.packs.pack_file import FILE_ALTERED

    target = ctx.temp / "corrupt" / packs_import.CORRUPT_PACK
    changed = packs_import.make_corrupt_copy(source, target)
    reason = FILE_ALTERED.format(path=changed.relative_to(target).as_posix())
    expected = s.PACK_IMPORT_REJECTED.format(reason=reason)
    started = packs_import.start_import(app, packs_import.CORRUPT_PACK, target)
    if started is not None:
        checks.append(check("corrupt-copy-refused", False, started))
        return False
    probe = lambda: ui.shows(app.nodes(), expected)
    if not ui.waited(checks, "corrupt-copy-refused", probe, ui.MODEL_TIMEOUT_S):
        return False
    model = packs_import.pack(packs_import.CORRUPT_PACK).model
    downloadable = lambda: packs_import.row_state(app.nodes(), model) == s.PACK_STATE_DOWNLOADABLE
    return ui.waited(checks, "corrupt-copy-left-downloadable", downloadable)


def _import_all(app: Any, sources: dict[str, Path], checks: list[Check]) -> bool:
    for pack_id, folder in sources.items():
        result = packs_import.import_folder(app, pack_id, folder)
        ok = result == "validated"
        checks.append(check(f"import-{pack_id}-validated", ok, None if ok else result))
        if not ok:
            return False
    return True


def _protection(app: Any, s: Any, source: Path, checks: list[Check]) -> bool:
    running = s.SESSION_RUNNING.format(mode=s.NAV_CONVERSATION)
    if not e03._cable_microphone(app, s, checks):
        return False
    if not ui.select(app, s.NAV_CONVERSATION, s.NAV_REGION):
        checks.append(check("conversation-running", False, "not-selected"))
        return False
    app.keys("{F8}")
    if not ui.waited(
        checks, "conversation-running", lambda: ui.shows(app.nodes(), running), ui.MODEL_TIMEOUT_S
    ):
        return False
    model = packs_import.pack(RECOGNITION).model
    if not ui.select(app, s.NAV_LANGUAGE_PACKS, s.NAV_REGION):
        checks.append(check("remove-refused-while-running", False, "packs-page-not-shown"))
        return False
    if not provisioning.remove(app, model, checks, "remove-refused-while-running"):
        return False
    refused = s.PACK_IN_USE.format(mode=s.NAV_CONVERSATION)
    if not ui.waited(
        checks, "remove-refused-while-running", lambda: ui.shows(app.nodes(), refused)
    ):
        return False
    kept = packs_import.row_state(app.nodes(), model) == s.PACK_STATE_VALIDATED
    checks.append(check("validated-while-running", kept))
    app.keys("{F9}")
    if not ui.waited(checks, "stopped", lambda: e03._strip_gone(app.nodes(), s, running)):
        return False
    if not provisioning.remove(app, model, checks, "removed-after-stop"):
        return False
    removed = packs_import.wait_state(app, RECOGNITION, s.PACK_STATE_DOWNLOADABLE)
    checks.append(check("removed-after-stop", removed))
    if not removed:
        return False
    result = packs_import.import_folder(app, RECOGNITION, source)
    checks.append(check("reimport-validated", result == "validated", result))
    return result == "validated"


def _group(ctx, app, folder: Path, sources: dict[str, Path], checks, artifacts) -> None:
    s = ui.strings()
    corrupt = sources[packs_import.CORRUPT_PACK]
    _corrupt(ctx, app, s, corrupt, checks)  # a failure here still lets the imports run
    if not _import_all(app, sources, checks):
        return
    recorded = manifest_sources(folder)
    imported = all(recorded.get(pack_id) == "import" for pack_id in sources)
    checks.append(check("manifest-source-import", imported, f"records={len(recorded)}"))
    shot, artifact = provisioning.shot(ctx, app, SCREEN, "screenshot-masked")
    checks.append(shot)
    artifacts.append(artifact)
    _protection(app, s, sources[RECOGNITION], checks)


def all_validated(app: Any, s: Any) -> bool:
    """Whether Language packs shows every pair pack *Validated* (E-19's precondition)."""
    if not ui.select(app, s.NAV_LANGUAGE_PACKS, s.NAV_REGION):
        return False
    models = [packs_import.pack(pack_id).model for pack_id in provisioning.pair_ids()]
    found = provisioning.states(app.nodes(), models)
    return bool(found) and all(state == s.PACK_STATE_VALIDATED for state in found)


def _e19(ctx: RunContext, app: Any, ready: bool) -> Row:
    if not ready:
        return blocked_row("E-19", "e18-packs-not-validated")
    s = ui.strings()
    if ui.shows(app.nodes(), s.SESSION_RUNNING.format(mode=s.NAV_CONVERSATION)):
        app.keys("{F9}")  # a failed E-18 step left the session running
    try:
        return e19.session(ctx, app)
    except Exception as error:  # noqa: BLE001 - recorded as E-19's failure, E-18 stands
        return error_row("E-19", error)


def run(ctx: RunContext) -> Row:
    sources = {
        pack_id: packs_import.image_pack_dir(ctx, pack_id) for pack_id in provisioning.pair_ids()
    }
    if not all(packs_import.has_pack_file(folder) for folder in sources.values()):
        ctx.state[e19.KEY] = blocked_row("E-19", packs_import.PACK_FILE_MISSING)
        return blocked_row("E-18", packs_import.PACK_FILE_MISSING)
    checks: list[Check] = []
    artifacts: list = []
    ctx.state[e19.KEY] = blocked_row("E-19", "e18-group-not-finished")
    uia_app.close_open(ctx)
    try:
        with models_swap.scratch_models(ctx, GROUP) as folder:
            app = uia_app.launch(ctx)
            try:
                _group(ctx, app, folder, sources, checks, artifacts)
                ctx.state[e19.KEY] = _e19(ctx, app, all_validated(app, ui.strings()))
            finally:
                app.close()
    finally:
        checks.append(check("settings-baseline-restored", uia_app.settings_reset(ctx)))
    return make_row("E-18", checks, artifacts, reason="pack-import")
