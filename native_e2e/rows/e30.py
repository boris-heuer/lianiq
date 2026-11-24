"""E-30: one voice missing, then legacy text-only settings (CAP-0167 e2e plan E-05..E-07).

Fixtures first (``conv_de_16k.wav``, ``conv_zh_16k.wav`` through ``synth.speech_wav``; the
Mandarin one is synthesised before the junction moves), and the image folder of every
German–Mandarin pack but the Mandarin voice (``packs``; packs of other pairs, such as
english-mandarin-pair, are left out) must hold ``lianiq-pack.json`` (else ``blocked`` with
``image-packs-without-pack-file``). Scratch group ``e30`` (``models_swap``): its own app
imports those packs (``packs_import.import_folder``, each *Validated*). Conversation: the
Mandarin switch is off and disabled and its state reads "Voice missing"; **Open Language
packs** of that row opens Language packs, and the sidebar leads back. Cable Microphone and
Speakers, the German switch on, **Start**; the German fixture gives a Mandarin translation
shown as text only, the Mandarin fixture a German one that is spoken: the log of the session
has completed playbacks in German only. F9, a masked screenshot, then Settings ›
Diagnostics lists "Voice German: Ready" and "Voice Mandarin (Simplified): Voice missing".
The app is closed and the junction restored (also on an error). Then, on the image models,
the local settings become the legacy file of plan D-02 (``legacy-settings.template.json``
plus ``languages.output: "text"``, no ``tts.output``); after a launch both switches are on.
The settings are reset to the S-03 baseline at the end.
"""

from __future__ import annotations

import json

from native_e2e import models_swap, packs_import, synth, uia_app
from native_e2e.context import RunContext
from native_e2e.evidence.model import Check, Method, Row
from native_e2e.rows import e03, e11, e15, ui, voice
from native_e2e.rows.common import blocked_row, check, make_row
from native_e2e.rows.voice import GERMAN, MANDARIN

FIXTURES = ("conv_de_16k.wav", "conv_zh_16k.wav")
GROUP = "e30"
SCREEN = "screens/e30-voice-missing.png"


def packs() -> list[str]:
    """Every German–Mandarin pack (recognition for both, both edges, the German voice) but
    the Mandarin voice; packs of other pairs are never imported."""
    from lianiq.packs.catalog import PackKind

    pair = {GERMAN, MANDARIN, f"{GERMAN}>{MANDARIN}", f"{MANDARIN}>{GERMAN}"}

    def keep(p) -> bool:
        if p.kind is PackKind.RECOGNITION:
            return {GERMAN, MANDARIN} <= set(p.provides)
        return set(p.provides) <= pair and not (p.kind is PackKind.VOICE and MANDARIN in p.provides)

    return [p.id for p in packs_import.catalog().packs() if keep(p)]


def _missing_row(nodes, s) -> bool:
    found = voice.switch(nodes, s, MANDARIN)
    shown = voice.state_shows(nodes, s, MANDARIN, s.VOICE_STATE_MISSING)
    return found is not None and not found.enabled and found.selected is False and shown


def _packs_and_back(app, s, checks: list[Check]) -> bool:
    button = ui.find(app.nodes(), s.VOICE_PACKS_NAME.format(language=voice.name(MANDARIN)))
    if button is None:
        checks.append(check("open-language-packs", False, "not-shown"))
        return False
    app.press(button)
    on_packs = lambda: any(
        n.name == s.NAV_LANGUAGE_PACKS and n.selected for n in ui.sidebar(app.nodes(), s.NAV_REGION)
    )
    if not ui.waited(checks, "open-language-packs", on_packs):
        return False
    back = ui.select(app, s.NAV_CONVERSATION, s.NAV_REGION)
    checks.append(check("back-to-conversation", back))
    return back


def _german_on(app, s, checks: list[Check]) -> bool:
    found = voice.switch(app.nodes(), s, GERMAN)
    if found is not None and found.enabled and found.selected is not True:
        app.press(found)
    on = lambda: voice.switches_on(app.nodes(), s, (GERMAN,))
    return ui.waited(checks, "german-switch-on", on)


def _session(ctx, app, paths, checks: list[Check], artifacts: list) -> None:
    s = ui.strings()
    for pack_id in packs():
        result = packs_import.import_folder(app, pack_id, packs_import.image_pack_dir(ctx, pack_id))
        if result != "validated":
            checks.append(check("packs-imported", False, f"{pack_id}: {result}"))
            return
    checks.append(check("packs-imported", True, f"count={len(packs())}"))
    if not ui.select(app, s.NAV_CONVERSATION, s.NAV_REGION):
        checks.append(check("mandarin-switch-voice-missing", False, "not-selected"))
        return
    probe = lambda: _missing_row(app.nodes(), s)
    if not ui.waited(checks, "mandarin-switch-voice-missing", probe):
        return
    if not _packs_and_back(app, s, checks) or not voice.cable_devices(app, s, checks):
        return
    if not ui.select(app, s.NAV_CONVERSATION, s.NAV_REGION) or not _german_on(app, s, checks):
        return
    offset = e15.log_size(ctx)
    if not voice.start(app, s, checks):
        return
    text_only = voice.watch_turn(ctx, app, s, paths[0], spoken_turn=False)
    turn = voice.watch_turn(ctx, app, s, paths[1]) if text_only is not None else None
    checks.append(check("both-turns-shown", turn is not None))
    if turn is None:
        return
    languages = set(voice.spoken(e15.log_since(ctx, offset)))
    checks.append(check("german-spoken-mandarin-text-only", languages == {GERMAN}))
    app.keys("{F9}")
    running = s.SESSION_RUNNING.format(mode=s.NAV_CONVERSATION)
    if not ui.waited(checks, "stopped", lambda: e03._strip_gone(app.nodes(), s, running)):
        return
    shot, artifact = ui.screenshot(ctx, app, SCREEN, "screenshot-voice-missing-masked")
    checks.append(shot)
    artifacts.append(artifact)
    rows = [
        voice.readiness_row(s, GERMAN, s.DIAG_READY),
        voice.readiness_row(s, MANDARIN, s.VOICE_STATE_MISSING),
    ]
    if not ui.select(app, s.NAV_SETTINGS, s.NAV_REGION):
        checks.append(check("diagnostics-voice-missing", False, "not-selected"))
        return
    ready = lambda: all(row in voice.readiness(app, s) for row in rows)
    ui.waited(checks, "diagnostics-voice-missing", ready)


def _legacy(ctx, checks: list[Check]) -> None:
    data = json.loads(e11.TEMPLATE.read_text(encoding="utf-8"))
    data["languages"] = {"output": "text"}
    ctx.local_settings.write_text(json.dumps(data, indent=2), encoding="utf-8")
    checks.append(check("legacy-text-settings-written", ctx.local_settings.is_file()))
    app = uia_app.launch(ctx)
    try:
        s = ui.strings()
        if not ui.select(app, s.NAV_CONVERSATION, s.NAV_REGION):
            checks.append(check("legacy-switches-on", False, "not-selected"))
            return
        ui.waited(checks, "legacy-switches-on", lambda: voice.switches_on(app.nodes(), s))
    finally:
        app.close()


def run(ctx: RunContext) -> Row:
    paths = [synth.speech_wav(ctx, name) for name in FIXTURES]
    if None in paths:
        missing = ",".join(n for n, p in zip(FIXTURES, paths, strict=True) if p is None)
        return blocked_row("E-30", synth.FIXTURE_MISSING, missing)
    if not all(packs_import.has_pack_file(packs_import.image_pack_dir(ctx, p)) for p in packs()):
        return blocked_row("E-30", packs_import.PACK_FILE_MISSING)
    checks: list[Check] = [check("fixtures-checked", True)]
    artifacts: list = []
    uia_app.close_open(ctx)
    try:
        with models_swap.scratch_models(ctx, GROUP):
            app = uia_app.launch(ctx)
            try:
                _session(ctx, app, paths, checks, artifacts)
            finally:
                app.close()
        _legacy(ctx, checks)
    finally:
        checks.append(check("settings-reset", uia_app.settings_reset(ctx)))
    return make_row("E-30", checks, artifacts, reason="voice-missing", method=Method.VIRTUAL_DEVICE)
