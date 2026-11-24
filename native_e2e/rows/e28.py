"""E-28: spoken turns, Replay and Voice options measured on the cable (CAP-0167 E-02, E-03).

Fixtures first: ``conv_zh_16k.wav`` and ``conv_de_16k.wav`` through ``synth.speech_wav``
(pinned file, else synthesised in the VM; ``blocked`` with ``fixture-missing`` otherwise).
Then its own app: "CABLE Output" as Microphone, "CABLE Input" as Speakers, both voice
switches on, **Start** (F8). Deviation from the spec order: the Mandarin fixture is played first and the German one second,
so the last spoken translation is Mandarin and the Mandarin Rate below changes what
**Replay** speaks (with German last, the Rate change could not be measured). Per turn
(``voice.watch_turn``): the new turn is in the panels on every poll showing "Microphone
paused while the translation is spoken" (text before speech), the paused state shows and
the level bar reads 0 meanwhile; the app log of both turns has a completed playback in both
languages. **Replay** is recorded on the cable (speech duration); Mandarin **Voice
options…** shows only Voice and Rate; Rate is set to 1.30× (the local settings then hold
``tts.output["zh-Hans"].rate`` 1.3); **Replay** again: the second duration is at most 0.85 ×
the first. German **Voice options…** shows only Rate and Volume. Stored: durations, their
ratio, the rate and one masked screenshot; never PCM, a text or a log line. At the end the
app is closed and the settings reset to the S-03 baseline (the rate is restored).
"""

from __future__ import annotations

from native_e2e import synth, uia_app
from native_e2e.context import RunContext
from native_e2e.evidence.model import Check, Method, Row
from native_e2e.rows import e15, ui, voice
from native_e2e.rows.common import blocked_row, check, make_row
from native_e2e.rows.voice import GERMAN, MANDARIN

FIXTURES = ("conv_zh_16k.wav", "conv_de_16k.wav")
RATE = 1.3
MAX_RATIO = 0.85
SCREEN = "screens/e28-spoken.png"


def _turns(ctx, app, s, paths, checks: list[Check]) -> bool:
    offset = e15.log_size(ctx)
    seen = []
    for path in paths:
        found = voice.watch_turn(ctx, app, s, path)
        if found is None:
            checks.append(check("turns-spoken", False, "timeout"))
            return False
        seen.append(found)
    languages = set(voice.spoken(e15.log_since(ctx, offset)))
    checks += [
        check("turns-spoken", True),
        check("text-before-speech", all(item["text_first"] for item in seen)),
        check("paused-during-speech", all(item["paused_seen"] for item in seen)),
        check("level-zero-during-speech", all(item["level_zero"] for item in seen)),
        check("both-directions-spoken", {GERMAN, MANDARIN} <= languages),
    ]
    return True


def _replay(ctx, app, s) -> float | None:
    button = ui.find(app.nodes(), s.VOICE_REPLAY, "Button")
    if button is None or not button.enabled:
        return None
    offset = e15.log_size(ctx)

    def done() -> bool:
        again = ui.find(app.nodes(), s.VOICE_REPLAY, "Button")
        idle = again is not None and again.enabled
        return idle and bool(voice.spoken(e15.log_since(ctx, offset)))

    return voice.measure(lambda: app.press(button), done)


def _rate(ctx, app, s, checks: list[Check]) -> bool:
    nodes = voice.open_options(app, s, MANDARIN)
    if nodes is None:
        checks.append(check("mandarin-options-voice-and-rate", False, "not-opened"))
        return False
    shown = voice.controls(nodes, s)
    checks.append(
        check("mandarin-options-voice-and-rate", shown == ["voice", "rate"], ",".join(shown))
    )
    title = s.VOICE_OPTIONS_TITLE.format(language=voice.name(MANDARIN))
    slider = ui.find(nodes, s.VOICE_RATE, "Slider")
    if slider is None:
        return False
    app.set_value(slider, round(RATE * 100))
    text = s.VOICE_RATE_VALUE.format(value=RATE)

    def applied() -> bool:
        found = ui.find(app.window_nodes(title) or (), s.VOICE_RATE, "Slider")
        return (
            found is not None
            and text in found.description
            and voice.settings_rate(ctx, MANDARIN) == RATE
        )

    ok = ui.waited(checks, "mandarin-rate-1.30-saved", applied)
    return voice.close_options(app, s, MANDARIN) and ok


def _german_options(app, s, checks: list[Check]) -> None:
    nodes = voice.open_options(app, s, GERMAN)
    shown = voice.controls(nodes, s) if nodes is not None else []
    detail = ",".join(shown) if nodes is not None else "not-opened"
    checks.append(check("german-options-rate-and-volume", shown == ["rate", "volume"], detail))
    if nodes is not None:
        voice.close_options(app, s, GERMAN)


def _session(ctx, app, paths, checks: list[Check], artifacts: list) -> None:
    s = ui.strings()
    if not (voice.cable_devices(app, s, checks) and e15._voice_output_on(app, s, checks)):
        return
    if not voice.start(app, s, checks) or not _turns(ctx, app, s, paths, checks):
        return
    shot, artifact = ui.screenshot(ctx, app, SCREEN, "screenshot-spoken-masked")
    checks.append(shot)
    artifacts.append(artifact)
    first = _replay(ctx, app, s)
    checks.append(check("replay-recorded", first is not None, f"duration_s={first}"))
    if first is None or not _rate(ctx, app, s, checks):
        return
    second = _replay(ctx, app, s)
    ratio = round(second / first, 3) if second is not None and first > 0 else None
    detail = f"first_s={first} second_s={second} ratio={ratio}"
    checks.append(
        check("replay-faster-at-rate-1.30", ratio is not None and ratio <= MAX_RATIO, detail)
    )
    _german_options(app, s, checks)


def run(ctx: RunContext) -> Row:
    paths = [synth.speech_wav(ctx, name) for name in FIXTURES]
    if None in paths:
        missing = ",".join(n for n, p in zip(FIXTURES, paths, strict=True) if p is None)
        return blocked_row("E-28", synth.FIXTURE_MISSING, missing)
    checks: list[Check] = [check("fixtures-checked", True)]
    artifacts: list = []
    uia_app.close_open(ctx)
    app = uia_app.launch(ctx)
    try:
        _session(ctx, app, paths, checks, artifacts)
    finally:
        app.close()
        checks.append(check("settings-reset", uia_app.settings_reset(ctx)))
    return make_row("E-28", checks, artifacts, reason="spoken-replay", method=Method.VIRTUAL_DEVICE)
