"""E-20..E-22: Text translation from an empty models folder (CAP-0172 e2e plan E-01..E-04).

One scratch-model group (``models_swap.scratch_models(ctx, "e20")``) and one app for the
three rows; the junction and the S-03 settings baseline (``uia_app.settings_reset``) come
back at the end, also when a row raises. Every source must hold ``lianiq-pack.json``, else
all three rows are ``blocked`` with ``image-packs-without-pack-file`` before anything changes.

E-20 (plan E-01, import instead of download): no settings file, so the setup assistant opens
(``launch(setup_assistant=True)``). *What do you want to do?*: only **Text translation**
ticked; **Next**; German and Mandarin (Simplified); **Next**; *Audio check* **Next**;
*Readiness* lists both voices *Optional — for spoken output*, no speech recognition row and no
microphone row; each translation row's **Get…** opens the pack dialog, where the licence box,
**Import…** › **Choose folder…** import the image folder (``packs_import``) until the row reads
*Ready*; **Finish**. ``model-manifest.json`` then holds exactly the two translation packs. On
the Text translation page D-03 is translated without restart. Screenshots: usage, readiness
and the result, both panes masked. E-21 and E-22 are in ``rows/e21.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from native_e2e import models_swap, packs_import, uia_app
from native_e2e.context import RunContext
from native_e2e.evidence.model import Check, Method, Row
from native_e2e.rows import e21, text_flow, ui
from native_e2e.rows.common import blocked_row, check, error_row, make_row
from native_e2e.rows.e21 import VOICE_PACKS
from native_e2e.rows.text_flow import GERMAN, MANDARIN, assistant, label, name, review_rows
from native_e2e.uia import Node

GROUP = ("E-20", "E-21", "E-22")
STATE_KEY = "e20_group"
TRANSLATION_PACKS = tuple(text_flow.TRANSLATION_EDGES)
TEXT_USAGE = "text-translation"  # lianiq.packs.usage profile id
SCREENS = ("screens/e20-usage.png", "screens/e20-readiness.png", "screens/e20-result.png")
NOT_READY = "translation-packs-not-ready"  # E-21/E-22 blocked when E-20 got no translation


def _step(app: Any, s: Any, title: str) -> bool:
    """**Next**, then wait for the step titled ``title``."""
    found = ui.find(assistant(app, s), s.ASSIST_NEXT, "Button")
    if found is None or not found.enabled:
        return False
    app.press(found)
    try:
        ui.wait(lambda: ui.find(assistant(app, s), title, "Text"))
    except TimeoutError:
        return False
    return True


def _usage(app: Any, s: Any) -> bool:
    from lianiq.packs.usage import USAGE_PROFILES
    from lianiq.ui.setup_assistant.step_usage import usage_text

    wanted = {usage_text(p): p.id == TEXT_USAGE for p in USAGE_PROFILES}

    def boxes() -> list[Node]:
        return [n for n in assistant(app, s) if n.control_type == "CheckBox" and n.name in wanted]

    for box in boxes():
        if box.enabled and bool(box.selected) != wanted[box.name]:
            app.press(box)

    def only_text() -> bool:
        found = boxes()
        return bool(found) and all(bool(b.selected) == wanted[b.name] for b in found)

    try:
        ui.wait(only_text)
    except TimeoutError:
        return False
    return True


def _languages(app: Any, s: Any) -> bool:
    lists = ((s.ASSIST_LANG_FIRST, name(GERMAN)), (s.ASSIST_LANG_SECOND, name(MANDARIN)))

    def item(nodes: list[Node], owner: str, wanted: str) -> Node | None:
        return next(
            (
                n
                for n in nodes
                if n.visible
                and n.control_type == "ListItem"
                and n.name == wanted
                and owner in n.parents
            ),
            None,
        )

    for owner, wanted in lists:
        found = item(assistant(app, s), owner, wanted)
        if found is None:
            return False
        if not found.selected:
            app.press(found)
    try:
        ui.wait(
            lambda: all((item(assistant(app, s), o, w) or Node("", "")).selected for o, w in lists)
        )
    except TimeoutError:
        return False
    return True


def _readiness(app: Any, s: Any, checks: list[Check]) -> bool:
    try:
        rows = ui.wait(lambda: review_rows(assistant(app, s), s))
    except TimeoutError:
        checks.append(check("readiness-shown", False, "timeout"))
        return False
    voices = [label("voice", lang) for lang in (GERMAN, MANDARIN)]
    optional = all(
        any(r.startswith(v) and r.endswith(s.ASSIST_OPTIONAL_VOICE) for r in rows) for v in voices
    )
    absent = [label("recognition", lang) for lang in (GERMAN, MANDARIN)]
    absent.append(label("microphone"))
    none = not any(r.startswith(f"{a} — ") for r in rows for a in absent)
    checks += [
        check("readiness-voices-optional", optional),
        check("readiness-no-recognition-no-microphone", none),
    ]
    return True


def _import(app: Any, s: Any, pack_id: str, folder: Path) -> str:
    """Readiness row **Get…** › the pack dialog's import (``packs_import`` steps) › *Ready*."""
    definition = packs_import.pack(pack_id)
    lead = label("translation", pack_id)
    get = next(
        (
            n
            for n in assistant(app, s)
            if n.control_type == "Button"
            and n.enabled
            and n.name == s.PACK_GET
            and n.description.startswith(lead)
        ),
        None,
    )
    if get is None:
        return "get-not-shown"
    app.press(get)
    try:
        ui.wait(lambda: app.window_nodes(definition.model))
    except TimeoutError:
        return "details-not-opened"
    reason = packs_import._accept_licence(app, s, definition) or packs_import._choose_folder(
        app, s, definition.model, folder
    )
    if reason is not None:
        return reason
    try:
        ui.wait(lambda: app.window_nodes(definition.model) is None)
    except TimeoutError:
        return "details-not-closed"
    ready = f"{lead} — {s.ASSIST_REVIEW_READY} — "
    try:
        ui.wait(
            lambda: any(r.startswith(ready) for r in review_rows(assistant(app, s), s)),
            ui.MODEL_TIMEOUT_S,
        )
    except TimeoutError:
        return "not-ready"
    return "ready"


def _manifest(folder: Path) -> set[str] | None:
    try:
        data = json.loads((folder / "model-manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return {str(record.get("id")) for record in data.get("packs", [])}


def _e20(ctx: RunContext, app: Any, folders: dict, scratch: Path, artifacts: list) -> list:
    s, checks = ui.strings(), []
    try:
        ui.wait(lambda: ui.find(assistant(app, s), s.ASSIST_USAGE_TITLE, "Text"))
    except TimeoutError:
        return [check("assistant-opened", False, "timeout")]
    checks.append(check("assistant-opened", True))
    checks.append(check("only-text-translation-ticked", _usage(app, s)))
    shot, artifact = text_flow.shot(ctx, app, SCREENS[0], (), "screenshot-usage-masked")
    checks.append(shot)
    artifacts.append(artifact)
    if not _step(app, s, s.ASSIST_LANG_TITLE):
        return [*checks, check("languages-german-mandarin", False, "not-shown")]
    checks.append(check("languages-german-mandarin", _languages(app, s)))
    for title in (s.ASSIST_AUDIO_TITLE, s.ASSIST_REVIEW_TITLE):
        if not _step(app, s, title):
            return [*checks, check("readiness-shown", False, "not-shown")]
    if not _readiness(app, s, checks):
        return checks
    shot, artifact = text_flow.shot(ctx, app, SCREENS[1], (), "screenshot-readiness-masked")
    checks.append(shot)
    artifacts.append(artifact)
    for pack_id in TRANSLATION_PACKS:
        outcome = _import(app, s, pack_id, folders[pack_id])
        checks.append(check(f"imported-{pack_id}", outcome == "ready", outcome))
        if outcome != "ready":
            return checks
    finish = ui.find(assistant(app, s), s.ASSIST_FINISH, "Button")
    if finish is None:
        return [*checks, check("finished", False, "not-shown")]
    app.press(finish)
    if not ui.waited(checks, "finished", lambda: app.window_nodes(s.ASSIST_TITLE) is None):
        return checks
    packs = _manifest(scratch)
    only = packs == set(TRANSLATION_PACKS)
    checks.append(check("manifest-translation-packs-only", only, f"packs={len(packs or ())}"))
    if not text_flow.open_page(app, s, checks, "translation-shown-without-restart"):
        return checks
    if not text_flow.direction(app, s, GERMAN, MANDARIN):
        return [*checks, check("translation-shown-without-restart", False, "direction")]
    if not text_flow.type_source(app, s, text_flow.D03):
        return [*checks, check("translation-shown-without-restart", False, "not-typed")]
    text_flow.remember(ctx, text_flow.D03)
    result = text_flow.translated(ctx, app, s, checks, "translation-shown-without-restart")
    if result is not None:
        shot, artifact = text_flow.shot(ctx, app, SCREENS[2], result, "screenshot-result-masked")
        checks.append(shot)
        artifacts.append(artifact)
        ctx.state["e20_translated"] = True
    return checks


def _guarded(row_id: str, step, method: Method, reason: str) -> Row:
    artifacts: list = []
    try:
        checks = step(artifacts)
    except Exception as error:  # noqa: BLE001 - recorded as this row's failure, never retried
        return error_row(row_id, error)
    return make_row(row_id, checks, artifacts, reason=reason, method=method)


def _group(ctx: RunContext) -> dict[str, Row]:
    packs = (*TRANSLATION_PACKS, *VOICE_PACKS)
    folders = {pack_id: packs_import.image_pack_dir(ctx, pack_id) for pack_id in packs}
    if not all(packs_import.has_pack_file(folder) for folder in folders.values()):
        return {r: blocked_row(r, packs_import.PACK_FILE_MISSING) for r in GROUP}
    ctx.state.pop("e20_translated", None)
    rows: dict[str, Row] = {}
    try:
        with models_swap.scratch_models(ctx, "e20") as scratch:
            app = uia_app.launch(ctx, setup_assistant=True)
            try:
                rows["E-20"] = _guarded(
                    "E-20",
                    lambda a: _e20(ctx, app, folders, scratch, a),
                    Method.NATIVE,
                    "text-translation-first-run",
                )
                if not ctx.state.get("e20_translated"):
                    return {**rows, **{r: blocked_row(r, NOT_READY) for r in GROUP[1:]}}
                rows["E-21"] = _guarded(
                    "E-21", lambda a: e21.e21(ctx, app, a), Method.NATIVE, "text-no-voices"
                )
                rows["E-22"] = _guarded(
                    "E-22",
                    lambda a: e21.e22(ctx, app, folders, a),
                    Method.VIRTUAL_DEVICE,
                    "text-copy-play-stale",
                )
            finally:
                app.close()
    finally:
        uia_app.settings_reset(ctx)
    return rows


def run(ctx: RunContext) -> Row:
    """E-20; runs the whole group and keeps E-21 and E-22 for ``run_e21``/``run_e22``."""
    try:
        rows = _group(ctx)
    except Exception as error:  # noqa: BLE001 - the junction is back (scratch_models)
        rows = {row_id: error_row(row_id, error) for row_id in GROUP}
    ctx.state[STATE_KEY] = rows
    return rows["E-20"]


def _later(ctx: RunContext, row_id: str) -> Row:
    return ctx.state.get(STATE_KEY, {}).get(row_id) or blocked_row(row_id, "group-not-run")


def run_e21(ctx: RunContext) -> Row:
    return _later(ctx, "E-21")


def run_e22(ctx: RunContext) -> Row:
    return _later(ctx, "E-22")
