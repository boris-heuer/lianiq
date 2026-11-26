"""E-39: the three English packs on the image models (english-mandarin-pair 9-E-01, AC-03, AC-06).

The e2e plan row gets the packs over the network; the VM has none, so E-39 reads the packs the
image already holds (spec §2.3: an image rebuilt after the English packs reached ``main``).
Before any app starts every file of ``mt-en-zh-hans``, ``mt-zh-hans-en`` and
``tts-en-us-ljspeech-high`` must be in the image's pack folders, else the row is ``blocked``
with ``english-packs-missing`` (E-40 uses the same gate).

``models/model-manifest.json`` of the image must hold each pack's record with a known source
(``download``, ``import``, ``script``), the catalog licence and, per catalog file, the pinned
SHA-256. In the app (image models, ``--no-setup-assistant``): Language packs shows each of the
three rows as *Validated* (one masked screenshot, the models folder line masked too);
Conversation's *Language pair* lists "English ↔ Mandarin (Simplified)" and no
"German ↔ English" (names from the registry and ``PAIR_NAME``). Nothing is selected, so no
setting changes. After the app is closed ``scripts\\doctor.py`` must exit 0; its log keeps
the output's SHA-256 and the duration only. Stored: states, counts, sources, booleans.
"""

from __future__ import annotations

from typing import Any

from native_e2e import audio, models_swap, packs_import, proc, screens, uia_app
from native_e2e.context import RunContext
from native_e2e.evidence.model import Artifact, Check, Row
from native_e2e.rows import ui
from native_e2e.rows.common import blocked_row, check, make_row
from native_e2e.uia import Node

ENGLISH_PACKS = ("mt-en-zh-hans", "mt-zh-hans-en", "tts-en-us-ljspeech-high")
MISSING = "english-packs-missing"  # a blocked reason (spec §2.3), not a failure
SCREEN = "screens/e39-language-packs.png"
DOCTOR_LOG = "logs/e39-doctor.txt"
DOCTOR_TIMEOUT_S = 600


def _present(ctx: RunContext, pack_id: str) -> bool:
    folder = packs_import.image_pack_dir(ctx, pack_id)
    files = packs_import.pack(pack_id).files
    return all(folder.joinpath(*item.path.split("/")).is_file() for item in files)


def packs_missing(ctx: RunContext) -> int:
    """How many English packs lack a file in the image (all of them when unreadable)."""
    try:
        return sum(1 for pack_id in ENGLISH_PACKS if not _present(ctx, pack_id))
    except (OSError, LookupError, ValueError):  # no image.json, or the catalog lacks a pack
        return len(ENGLISH_PACKS)


def pair_name(first: str, second: str) -> str:
    """The *Language pair* entry of two registry languages ("English ↔ Mandarin …")."""
    from lianiq.languages import BUILTIN_REGISTRY

    pair = BUILTIN_REGISTRY.pair(first, second)
    name = BUILTIN_REGISTRY.display_name
    return ui.strings().PAIR_NAME.format(a=name(pair.first), b=name(pair.second))


def _manifest(ctx: RunContext) -> Any:
    from lianiq.packs.manifest import Manifest

    return Manifest.read(models_swap.image_models(ctx) / "model-manifest.json")


def manifest_checks(ctx: RunContext) -> list[Check]:
    """Per pack: its record's source and licence and the pinned SHA-256 of every file."""
    from lianiq.packs.manifest import PACK_SOURCES

    try:
        manifest = _manifest(ctx)
    except Exception as error:  # noqa: BLE001 - ManifestError or OSError: no proof
        return [check("manifest-readable", False, type(error).__name__)]
    digests = manifest.digests()
    checks: list[Check] = []
    for pack_id in ENGLISH_PACKS:
        pack, record = packs_import.pack(pack_id), manifest.pack(pack_id)
        files = pack.files
        same = sum(1 for f in files if digests.get(f"{pack.root}/{f.path}") == f.sha256.lower())
        source = record.source if record is not None else None
        licence = record is not None and record.licence == pack.licence
        ok = source in PACK_SOURCES and licence and same == len(files)
        detail = f"source={source} licence={str(licence).lower()} sha256={same}/{len(files)}"
        checks.append(check(f"{pack_id}-source-licence-sha256", ok, detail))
    return checks


def combo_items(combo: Node) -> list[str]:
    """The item texts of a Qt combo box (listed only while it is expanded)."""

    def listed() -> list[str] | None:
        try:
            entries = combo.handle.descendants(control_type="ListItem")
            return [entry.element_info.name for entry in entries] or None
        except Exception:  # noqa: BLE001 - the popup is still opening: poll again
            return None

    combo.handle.expand()
    try:
        return ui.wait(listed)
    finally:
        try:
            combo.handle.collapse()
        except Exception:  # noqa: BLE001, S110 - already collapsed
            pass


def _packs_page(ctx: RunContext, app: Any, s: Any, checks: list[Check]) -> Artifact | None:
    if not ui.select(app, s.NAV_LANGUAGE_PACKS, s.NAV_REGION):
        checks.append(check("language-packs-shown", False, "not-selected"))
        return None
    for pack_id in ENGLISH_PACKS:
        model = packs_import.pack(pack_id).model
        ok = packs_import.wait_state(app, pack_id, s.PACK_STATE_VALIDATED)
        state = packs_import.row_state(app.nodes(), model)
        checks.append(check(f"{pack_id}-validated", ok, f"state={state}"))
    folder = s.PACKS_FOLDER.split("{path}")[0]  # the models path may name the user
    names = [*audio.endpoint_names(), folder, str(ctx.repo)]
    artifact, masked = screens.capture(ctx, app, SCREEN, names, (s.NOTICE_MICROPHONE,))
    checks.append(check("screenshot-masked", True, f"masked={masked}"))
    return artifact


def _pair_choice(app: Any, s: Any, checks: list[Check]) -> None:
    if not ui.select(app, s.NAV_CONVERSATION, s.NAV_REGION):
        checks.append(check("pair-choice", False, "not-selected"))
        return
    combo = ui.find(app.nodes(), s.PAIR_LABEL, "ComboBox")
    try:
        items = combo_items(combo) if combo is not None else None
    except Exception as error:  # noqa: BLE001 - TimeoutError or a UIA error: not listed
        items, detail = None, type(error).__name__
    else:
        detail = "not-listed" if items is None else f"items={len(items)}"
    wanted, unwanted = pair_name("en", "zh-Hans"), pair_name("de", "en")
    offered = items is not None and wanted in items
    checks.append(check("english-mandarin-offered", offered, detail))
    checks.append(check("german-english-not-offered", items is not None and unwanted not in items))


def doctor(ctx: RunContext) -> tuple[Check, Artifact]:
    import time

    started = time.monotonic()
    result = proc.run_tool([ctx.python, "scripts/doctor.py"], ctx.repo, DOCTOR_TIMEOUT_S)
    text = proc.digest_text(result, time.monotonic() - started)
    return proc.tool_check("doctor-exit-code-0", result), ctx.write_log(DOCTOR_LOG, text)


def run(ctx: RunContext) -> Row:
    absent = packs_missing(ctx)
    if absent:
        return blocked_row("E-39", MISSING, f"missing={absent}")
    checks, artifacts = manifest_checks(ctx), []
    s = ui.strings()
    uia_app.close_open(ctx)  # an app left open by an earlier row: E-39 needs its own
    app = uia_app.launch(ctx)
    try:
        shot = _packs_page(ctx, app, s, checks)
        artifacts += [shot] if shot is not None else []
        _pair_choice(app, s, checks)
    finally:
        app.close()
    result, log = doctor(ctx)
    checks.append(result)
    artifacts.append(log)
    return make_row("E-39", checks, artifacts, reason="english-packs")
