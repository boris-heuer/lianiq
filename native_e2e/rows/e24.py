"""E-24 and E-25: Listen & translate from an empty models folder (CAP-0170 e2e plan E-01..E-03).

One scratch-model group (``models_swap.scratch_models(ctx, "e24")``) and one app for both
rows; the junction (context manager) and the S-03 settings baseline (``settings_reset``) come
back in ``finally``, also when a row raises. Before anything changes, the image folders of the
German–Mandarin recognition pack and both translation packs (``listen_flow.packs``; packs of
other pairs, such as english-mandarin-pair, are never looked at) must hold
``lianiq-pack.json``, else both rows are ``blocked`` with ``image-packs-without-pack-file``.
The fixtures ``listen_de3_16k.wav`` and ``listen_zh_de_16k.wav`` come from
``synth.speech_wav`` first; without them E-25 is ``blocked`` with ``fixture-missing``.

E-24 (plan E-01): no settings file, so the setup assistant opens (``launch(setup_assistant=
True)``). *What do you want to do?*: only **Listen & translate**; **Next**; German and Mandarin
(Simplified); **Next**; *Audio check* **Next**; *Readiness* lists the recognition pack, both
translation packs and the microphone, no voice and no playback device. **Get…** imports the
recognition pack and ``de>zh-Hans`` from the image folders until each row reads *Ready*; the
``zh-Hans>de`` row still reads *Not installed* and **Finish** closes the assistant anyway.
``model-manifest.json`` then holds exactly those two packs. Screenshots of *Usage* and
*Readiness* (masked). E-25 is in ``rows/e25.py``; the runner takes its row from
``ctx.state`` (``e25.run``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from native_e2e import models_swap, packs_import, synth, uia_app
from native_e2e.context import RunContext
from native_e2e.evidence.model import Check, Method, Row
from native_e2e.rows import e25, ui
from native_e2e.rows import listen_flow as lf
from native_e2e.rows.common import blocked_row, check, error_row, make_row
from native_e2e.rows.listen_flow import GERMAN, MANDARIN, label

GROUP = ("E-24", "E-25")
STATE_KEY = e25.STATE_KEY
SCRATCH = "e24"
FIXTURES = ("listen_de3_16k.wav", "listen_zh_de_16k.wav")
SCREENS = ("screens/e24-usage.png", "screens/e24-readiness.png")
NOT_READY = "listen-packs-not-ready"  # E-25 blocked when E-24 got no German → Mandarin
FORWARD, BACKWARD = f"{GERMAN}>{MANDARIN}", f"{MANDARIN}>{GERMAN}"


def _readiness(rows: list[str], s: Any, checks: list[Check]) -> None:
    listed = [label("recognition", GERMAN), label("translation", FORWARD)]
    listed += [label("translation", BACKWARD), label("microphone")]
    absent = [label("voice", lang) for lang in (GERMAN, MANDARIN)] + [label("playback")]
    checks += [
        check("readiness-packs-and-microphone", all(lf.has_row(rows, item) for item in listed)),
        check("readiness-no-voice-no-speakers", not any(lf.has_row(rows, a) for a in absent)),
    ]


def _manifest(folder: Path) -> set[str] | None:
    try:
        data = json.loads((folder / "model-manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return {str(record.get("id")) for record in data.get("packs", [])}


def _shot(ctx: RunContext, app: Any, index: int, checks: list[Check], artifacts: list) -> None:
    shot, artifact = lf.shot(
        ctx, app, SCREENS[index], f"screenshot-{('usage', 'readiness')[index]}"
    )
    checks.append(shot)
    artifacts.append(artifact)


def e24(ctx: RunContext, app: Any, folders: dict, scratch: Path, artifacts: list) -> list[Check]:
    s, checks = ui.strings(), []
    try:
        ui.wait(lambda: ui.find(lf.assistant(app, s), s.ASSIST_USAGE_TITLE, "Text"))
    except TimeoutError:
        return [check("assistant-opened", False, "timeout")]
    checks += [check("assistant-opened", True), check("only-listen-ticked", lf.only_usage(app, s))]
    _shot(ctx, app, 0, checks, artifacts)
    if not lf.step(app, s, s.ASSIST_LANG_TITLE):
        return [*checks, check("languages-german-mandarin", False, "not-shown")]
    checks.append(check("languages-german-mandarin", lf.languages(app, s)))
    for title in (s.ASSIST_AUDIO_TITLE, s.ASSIST_REVIEW_TITLE):
        if not lf.step(app, s, title):
            return [*checks, check("readiness-shown", False, "not-shown")]
    try:
        rows = ui.wait(lambda: lf.review_rows(lf.assistant(app, s), s))
    except TimeoutError:
        return [*checks, check("readiness-shown", False, "timeout")]
    _readiness(rows, s, checks)
    _shot(ctx, app, 1, checks, artifacts)
    packs = lf.packs()
    leads = {"recognition": label("recognition", GERMAN), FORWARD: label("translation", FORWARD)}
    for role, lead in leads.items():
        outcome = lf.assistant_import(app, s, packs[role], lead, folders[role])
        checks.append(check(f"imported-{packs[role]}", outcome == "ready", outcome))
        if outcome != "ready":
            return checks
    rows = lf.review_rows(lf.assistant(app, s), s)
    backward = lf.has_row(rows, label("translation", BACKWARD), s.ASSIST_REVIEW_NOT_INSTALLED)
    finish = ui.find(lf.assistant(app, s), s.ASSIST_FINISH, "Button")
    if finish is None or not finish.enabled:
        return [*checks, check("finished-without-zh-hans-de", False, "not-enabled")]
    app.press(finish)
    closed = ui.waited(checks, "assistant-closed", lambda: not lf.assistant(app, s))
    checks.append(check("finished-without-zh-hans-de", closed and backward))
    found = _manifest(scratch)
    wanted = {packs["recognition"], packs[FORWARD]}
    checks.append(check("manifest-two-packs", found == wanted, f"packs={len(found or ())}"))
    ctx.state["e24_ready"] = closed and found == wanted
    return checks


def _guarded(row_id: str, step, method: Method, reason: str) -> Row:
    artifacts: list = []
    try:
        checks = step(artifacts)
    except Exception as error:  # noqa: BLE001 - recorded as this row's failure, never retried
        return error_row(row_id, error)
    return make_row(row_id, checks, artifacts, reason=reason, method=method)


def _group(ctx: RunContext) -> dict[str, Row]:
    packs = lf.packs()
    folders = {role: packs_import.image_pack_dir(ctx, pack_id) for role, pack_id in packs.items()}
    if len(packs) < 3 or not all(packs_import.has_pack_file(f) for f in folders.values()):
        return {r: blocked_row(r, packs_import.PACK_FILE_MISSING) for r in GROUP}
    paths = [synth.speech_wav(ctx, name) for name in FIXTURES]
    ctx.state.pop("e24_ready", None)
    rows: dict[str, Row] = {}
    uia_app.close_open(ctx)
    try:
        with models_swap.scratch_models(ctx, SCRATCH) as scratch:
            app = uia_app.launch(ctx, setup_assistant=True)
            try:
                rows["E-24"] = _guarded(
                    "E-24",
                    lambda a: e24(ctx, app, folders, scratch, a),
                    Method.NATIVE,
                    "listen-first-run",
                )
                if None in paths:
                    gone = ",".join(n for n, p in zip(FIXTURES, paths, strict=True) if p is None)
                    rows["E-25"] = blocked_row("E-25", synth.FIXTURE_MISSING, gone)
                elif not ctx.state.get("e24_ready"):
                    rows["E-25"] = blocked_row("E-25", NOT_READY)
                else:
                    rows["E-25"] = _guarded(
                        "E-25",
                        lambda a: e25.e25(ctx, app, paths, folders[BACKWARD], a),
                        Method.VIRTUAL_DEVICE,
                        "listen-both-directions",
                    )
            finally:
                app.close()
    finally:
        uia_app.settings_reset(ctx)
    return rows


def run(ctx: RunContext) -> Row:
    """E-24; runs the whole group and keeps E-25 for ``e25.run``."""
    try:
        rows = _group(ctx)
    except Exception as error:  # noqa: BLE001 - the junction is back (scratch_models)
        rows = {row_id: error_row(row_id, error) for row_id in GROUP}
    ctx.state[STATE_KEY] = rows
    return rows["E-24"]
