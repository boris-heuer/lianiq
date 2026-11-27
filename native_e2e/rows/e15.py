"""E-15: one spoken Conversation turn through the cable, stopped during playback (CAP-0167).

CAP-0167 AC-25, e2e plan C-02: the N-01 WAV is checked against ``image.json`` before any app
starts. Settings › Audio devices: "CABLE Output" as Microphone and "CABLE Input" as Speakers
(compared with the cable's WASAPI names; only ``name_matches`` is stored); Conversation:
every voice switch ("Speak {language}") is on, so a missing or invalid voice fails the row.
Then **Start** (F8), wait for "Conversation running" (300 s), play the WAV into "CABLE
Input" and wait until the turn is in the *Transcript* list, the state reads
"Microphone paused while the translation is spoken" and the app log has a completed
synthesis since the WAV was played (the next state is playback). F9 is pressed at once.

Pass rules: the strip is gone, the paused state is gone and **Stop playback** is disabled;
the log since F9 has "Microphone capture stopped" and a playback ended by the stop (a
playback that completed before F9 never logs one). The WAV is played into the cable once more: the log since F9 has no
"Microphone capture started" and the transcript (SHA-256 only) is unchanged. One masked
screenshot after the stop. The log stays in the checkout; the row stores no log line.
"""

from __future__ import annotations

from pathlib import Path

from native_e2e import audio, uia_app
from native_e2e.context import RunContext
from native_e2e.evidence.model import Check, Method, Row
from native_e2e.rows import e03, ui
from native_e2e.rows.common import check, make_row
from native_e2e.uia import Node

# Event lines of the app log (lianiq/audio/capture.py, lianiq/conversation/spoken_output.py).
CAPTURE_STARTED = "Microphone capture started"
CAPTURE_STOPPED = "Microphone capture stopped"
SYNTHESIZED = "Speech synthesis completed"
PLAYBACK_STOPPED = ("Audio playback stopped", "Audio playback ended by a stop")
SCREEN = "screens/e15-after-stop.png"


def log_path(ctx: RunContext) -> Path:
    return ctx.repo / "logs" / "lianiq.log"  # lianiq/app.py: PROJECT_ROOT / "logs"


def log_size(ctx: RunContext) -> int:
    try:
        return log_path(ctx).stat().st_size
    except OSError:
        return 0


def log_since(ctx: RunContext, offset: int) -> str:
    """The log text written after ``offset``; all of it after a rotation (a shorter file)."""
    try:
        data = log_path(ctx).read_bytes()
    except OSError:
        return ""
    return data[offset if len(data) >= offset else 0 :].decode("utf-8", errors="replace")


def _speakers(nodes: list[Node], s) -> str | None:
    combo = ui.find(nodes, s.NOTICE_SPEAKERS, "ComboBox")
    return combo.value if combo is not None else None


def _cable_speakers(app, s, checks: list[Check]) -> bool:
    """Settings › Audio devices: select "CABLE Input" as Speakers (name never stored)."""
    expected = audio.wasapi_name(audio.CABLE_INPUT, "output")
    matches = False
    if expected is not None and ui.select(app, s.NAV_SETTINGS, s.NAV_REGION):
        combo = ui.find(app.nodes(), s.NOTICE_SPEAKERS, "ComboBox")
        try:
            if combo is not None:
                app.choose(combo, expected)
                ui.wait_nodes(app, lambda nodes: _speakers(nodes, s) == expected)
                matches = True
        except Exception:  # noqa: BLE001 - not selectable (UIA/pywinauto error) or timeout
            matches = False
    checks.append(
        check("speakers-cable-selected", matches, f"name_matches: {str(matches).lower()}")
    )
    return matches


def _voice_output_on(app, s, checks: list[Check]) -> bool:
    """Conversation: every voice switch is enabled (voice ready) and turned on."""
    name = "voice-output-on"
    if not ui.select(app, s.NAV_CONVERSATION, s.NAV_REGION):
        checks.append(check(name, False, "not-selected"))
        return False
    switches = e03._voice_switches(app.nodes(), s)
    if not switches or not all(node.enabled for node in switches):
        checks.append(check(name, False, "not-ready" if switches else "not-found"))
        return False
    for switch in switches:
        if switch.selected is not True:
            app.press(switch)

    def on() -> bool:
        found = e03._voice_switches(app.nodes(), s)
        return bool(found) and all(node.selected is True for node in found)

    return ui.waited(checks, name, on)


def _stopped(nodes: list[Node], s, running: str) -> bool:
    button = ui.find(nodes, s.VOICE_STOP_PLAYBACK)
    return (
        e03._strip_gone(nodes, s, running)
        and not ui.shows(nodes, s.VOICE_MIC_PAUSED)
        and button is not None
        and not button.enabled
    )


def _ended_by_stop(text: str) -> bool:
    return CAPTURE_STOPPED in text and any(line in text for line in PLAYBACK_STOPPED)


def _session(ctx, app, path, checks: list[Check], artifacts: list) -> None:
    s = ui.strings()
    running = s.SESSION_RUNNING.format(mode=s.NAV_CONVERSATION)
    for step in (e03._cable_microphone, _cable_speakers, _voice_output_on):
        if not step(app, s, checks):
            return
    app.keys("{F8}")
    probe = lambda: ui.shows(app.nodes(), running)
    if not ui.waited(checks, "session-running", probe, ui.MODEL_TIMEOUT_S):
        return
    played = log_size(ctx)
    audio.play_into_cable(path)

    def speaking() -> bool:
        nodes = app.nodes()
        paused = ui.shows(nodes, s.VOICE_MIC_PAUSED) and e03.has_turn(nodes, s)
        return paused and SYNTHESIZED in log_since(ctx, played)

    if not ui.waited(checks, "translation-spoken", speaking, ui.MODEL_TIMEOUT_S):
        return
    before = e03.view(app.nodes(), s)
    e03._remember(ctx, before["texts"])
    stop = log_size(ctx)
    app.keys("{F9}")
    if not ui.waited(
        checks, "stopped-with-f9-during-playback", lambda: _stopped(app.nodes(), s, running)
    ):
        return
    if not ui.waited(
        checks, "playback-ended-by-stop", lambda: _ended_by_stop(log_since(ctx, stop))
    ):
        return
    audio.play_into_cable(path)  # the phrase again: a stopped session must not capture it
    text = log_since(ctx, stop)
    after = e03.view(app.nodes(), s)
    same = after["texts"] is not None and e03.digest(after["texts"]) == e03.digest(before["texts"])
    checks += [
        check("no-capture-after-stop", CAPTURE_STARTED not in text),
        check("transcript-sha256-unchanged", same, None if same else "changed"),
    ]
    shot, artifact = ui.screenshot(ctx, app, SCREEN, "screenshot-after-stop-masked")
    checks.append(shot)
    artifacts.append(artifact)


def run(ctx: RunContext) -> Row:
    try:
        path = audio.phrase_wav(ctx)
    except (OSError, ValueError, KeyError):
        checks = [check("test-phrase-sha256", False)]
        return make_row("E-15", checks, reason="test-phrase", method=Method.VIRTUAL_DEVICE)
    checks: list[Check] = [check("test-phrase-sha256", True)]
    artifacts: list = []
    uia_app.close_open(ctx)  # one app at a time: the cable and the log belong to this one
    app = uia_app.launch(ctx)
    try:
        _session(ctx, app, path, checks, artifacts)
    finally:
        app.close()
    return make_row("E-15", checks, artifacts, reason="spoken-output", method=Method.VIRTUAL_DEVICE)
