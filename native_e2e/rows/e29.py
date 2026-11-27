"""E-29: Stop playback and F9 during speech, measured on the cable (CAP-0167 e2e plan E-04).

``conv_de_16k.wav`` through ``synth.speech_wav`` (``blocked`` with ``fixture-missing``
otherwise). Its own app: cable Microphone and Speakers, both voice switches on, **Start**.
The cable is recorded (``audio.CableRecorder``) through both stops. Stop 1: the fixture is
played; once the translation plays (paused state, **Stop playback** enabled, a completed
synthesis in the log) the time is marked and **Stop playback** pressed; the log must show
the playback ended by the stop. After ``WINDOW_S`` of recording the fixture is played again
and, while it is spoken, the time is marked and F9 pressed; the strip and the paused state
must go and **Stop playback** be disabled. For each stop the last cable signal in the
``WINDOW_S`` after the mark must lie at most 0.5 s after it (the fixture itself is silent
by then). Then, with the fixture played once more into the cable, the state reads
"Stopped · {n} turns kept" (session-status-truthfulness; "Ready" is first launch only) and the
level bar 0 on every poll for 10 s, and the log has no "Microphone capture started"
after F9. Only the two latencies are stored; the samples stay in memory. The app is closed
and the settings reset to the S-03 baseline at the end.
"""

from __future__ import annotations

import time

from native_e2e import audio, synth, uia_app
from native_e2e.context import RunContext
from native_e2e.evidence.model import Check, Method, Row
from native_e2e.rows import e15, ui, voice
from native_e2e.rows.common import blocked_row, check, make_row

FIXTURE = "conv_de_16k.wav"
WINDOW_S = 1.5  # recorded after each stop; the latency must be ≤ MAX_LATENCY_S of it
MAX_LATENCY_S = 0.5
HOLD_S = 10.0


def _speaking(ctx, app, s, offset: int) -> bool:
    nodes = app.nodes()
    button = ui.find(nodes, s.VOICE_STOP_PLAYBACK, "Button")
    playing = button is not None and button.enabled and ui.shows(nodes, s.VOICE_MIC_PAUSED)
    return playing and e15.SYNTHESIZED in e15.log_since(ctx, offset)


def _stop(ctx, app, s, path, recorder, how: str, checks: list[Check]) -> tuple | None:
    """Play, wait for speech, mark and stop (``how``: "button" or "f9"): (mark, log offset
    at the key press), else ``None``."""
    offset = e15.log_size(ctx)
    thread = voice.play_async(path)
    try:
        if not ui.waited(
            checks,
            f"speaking-before-{how}",
            lambda: _speaking(ctx, app, s, offset),
            ui.MODEL_TIMEOUT_S,
        ):
            return None
        button = ui.find(app.nodes(), s.VOICE_STOP_PLAYBACK, "Button")
        mark, at_key = recorder.mark(), e15.log_size(ctx)
        if how == "f9":
            app.keys("{F9}")
            running = s.SESSION_RUNNING.format(mode=s.NAV_CONVERSATION)
            stopped = lambda: e15._stopped(app.nodes(), s, running)
        else:
            app.press(button)
            stopped = lambda: any(
                line in e15.log_since(ctx, offset) for line in e15.PLAYBACK_STOPPED
            )
        if not ui.waited(checks, f"stopped-with-{how}", stopped):
            return None
        ui.wait(lambda: recorder.mark() >= mark + WINDOW_S, WINDOW_S + ui.TIMEOUT_S)
        return mark, at_key
    finally:
        thread.join()


def latency(samples, rate: int, mark: float) -> float:
    """Seconds from ``mark`` to the last signal in the window after it (0 when silent)."""
    start = int(mark * rate)
    span = audio.speech_span(samples[start : start + int(WINDOW_S * rate)], rate)
    return round(span[1], 3) if span else 0.0


def _hold(ctx, app, s, path, offset: int, checks: list[Check]) -> None:
    thread = voice.play_async(path)
    ready, polls, deadline = True, 0, time.monotonic() + HOLD_S
    while time.monotonic() < deadline or polls == 0:
        nodes = app.nodes()
        ready &= voice.stopped(nodes) and voice.level(nodes) == 0
        polls += 1
        time.sleep(ui.POLL_S)
    thread.join()
    checks += [
        check("ready-and-level-zero-10s", ready, f"polls={polls}"),
        check("no-capture-after-f9", e15.CAPTURE_STARTED not in e15.log_since(ctx, offset)),
    ]


def _session(ctx, app, path, checks: list[Check]) -> None:
    s = ui.strings()
    if not (voice.cable_devices(app, s, checks) and e15._voice_output_on(app, s, checks)):
        return
    if not voice.start(app, s, checks):
        return
    recorder = audio.CableRecorder().start()
    marks: list[tuple] = []
    try:
        for how in ("button", "f9"):
            found = _stop(ctx, app, s, path, recorder, how, checks)
            if found is None:
                return
            marks.append(found)
    except TimeoutError:
        checks.append(check("cable-recorded", False, "timeout"))
        return
    finally:
        rate, samples = recorder.stop()
    for how, (mark, _offset) in zip(("button", "f9"), marks, strict=True):
        value = latency(samples, rate, mark)
        checks.append(check(f"last-signal-after-{how}", value <= MAX_LATENCY_S, f"seconds={value}"))
    _hold(ctx, app, s, path, marks[1][1], checks)


def run(ctx: RunContext) -> Row:
    path = synth.speech_wav(ctx, FIXTURE)
    if path is None:
        return blocked_row("E-29", synth.FIXTURE_MISSING, FIXTURE)
    checks: list[Check] = [check("fixture-checked", True)]
    uia_app.close_open(ctx)
    app = uia_app.launch(ctx)
    try:
        _session(ctx, app, path, checks)
    finally:
        app.close()
        checks.append(check("settings-reset", uia_app.settings_reset(ctx)))
    return make_row("E-29", checks, reason="stop-latency", method=Method.VIRTUAL_DEVICE)
