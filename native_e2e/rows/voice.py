"""Shared steps of the voice-output rows E-27..E-30 (CAP-0167; spec §2.2).

The voice row's accessible names come from ``lianiq.ui.strings_voice`` ("Speak {language}",
"{language} voice: {state}", "Voice options for {language}"); the language names from the
built-in registry. ``level`` reads the Conversation level bar through UIA RangeValue (Qt's
progress bar has no Value pattern). ``watch_turn`` polls one spoken turn until the app log
has one more completed playback: on every poll that shows the paused state ("Microphone
paused while the translation is spoken", shown from synthesis start) the new turn must
already be in the *Transcript* list and the level bar must read 0. ``measure`` records the cable around
one playback and returns its speech duration only (``audio.speech_span``), never samples.
Log lines are read in memory (``e15.log_since``) and never stored.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from native_e2e import audio, uia
from native_e2e.evidence.model import Check
from native_e2e.rows import e03, e15, ui
from native_e2e.uia import Node

GERMAN, MANDARIN = "de", "zh-Hans"  # registry language IDs of the image pair
READY_STATE = "Ready"  # Conversation's idle state (ui/workspaces/conversation.py, not a string)
PLAYED = re.compile(r"Audio playback completed: language=(\S+)")  # spoken_output.py


def name(language: str) -> str:
    from lianiq.languages import BUILTIN_REGISTRY
    from lianiq.languages.registry import LanguageId

    return BUILTIN_REGISTRY.display_name(LanguageId(language))


def switch(nodes: list[Node], s: Any, language: str) -> Node | None:
    return ui.find(nodes, s.VOICE_SWITCH_NAME.format(language=name(language)), "CheckBox")


def state_ready(nodes: list[Node], s: Any, language: str) -> bool:
    """The state label of ``language`` reads "{voice} · Ready" (any voice name)."""
    prefix = s.VOICE_STATE_NAME.format(language=name(language), state="")
    suffix = s.VOICE_READY.split("{voice}", 1)[1]
    return any(
        node.visible and node.name.startswith(prefix) and node.name.endswith(suffix)
        for node in nodes
    )


def state_shows(nodes: list[Node], s: Any, language: str, state: str) -> bool:
    return (
        ui.find(nodes, s.VOICE_STATE_NAME.format(language=name(language), state=state)) is not None
    )


def switches_on(nodes: list[Node], s: Any, languages=(GERMAN, MANDARIN)) -> bool:
    found = [switch(nodes, s, language) for language in languages]
    return all(node is not None and node.enabled and node.selected is True for node in found)


def _bar_value(node: Node) -> float | None:
    try:
        return float(node.value) if node.value is not None else None
    except ValueError:
        pass
    raw = getattr(node.handle, "iface_range_value", None)
    try:
        return float(raw.CurrentValue) if raw is not None else None
    except Exception:  # noqa: BLE001 - no RangeValue pattern
        return None


def level(nodes: list[Node]) -> float | None:
    """The highest shown progress bar value (the level bar); ``None`` when unreadable."""
    values = [_bar_value(n) for n in nodes if n.visible and n.control_type == "ProgressBar"]
    return max(values) if values and None not in values else None


def spoken(text: str) -> list[str]:
    """The language IDs of the completed playbacks in ``text``, in order."""
    return PLAYED.findall(text)


def play_async(path: Path) -> threading.Thread:
    """Play ``path`` into the cable without waiting, so the rows can poll meanwhile."""
    thread = threading.Thread(target=audio.play_into_cable, args=(path,), daemon=True)
    thread.start()
    return thread


def cable_devices(app: Any, s: Any, checks: list[Check]) -> bool:
    """ "CABLE Output" as Microphone and "CABLE Input" as Speakers (names never stored)."""
    return e03._cable_microphone(app, s, checks) and e15._cable_speakers(app, s, checks)


def start(app: Any, s: Any, checks: list[Check]) -> bool:
    app.keys("{F8}")
    running = s.SESSION_RUNNING.format(mode=s.NAV_CONVERSATION)
    return ui.waited(
        checks, "session-running", lambda: ui.shows(app.nodes(), running), ui.MODEL_TIMEOUT_S
    )


def texts_digest(nodes: list[Node], s: Any) -> str | None:
    texts = e03.view(nodes, s)["texts"]
    return e03.digest(texts) if texts is not None else None


def watch_turn(ctx: Any, app: Any, s: Any, path: Path, spoken_turn: bool = True) -> dict | None:
    """Play ``path`` and poll until a new turn is shown (and, if ``spoken_turn``, spoken and
    the paused state gone). Observations: ``text_first``, ``paused_seen``, ``level_zero``;
    ``None`` on a timeout. The transcript texts go to the secrets."""
    before = texts_digest(app.nodes(), s)
    offset, count = e15.log_size(ctx), 0
    seen = {"text_first": True, "paused_seen": False, "level_zero": True}

    def probe() -> bool:
        nodes = app.nodes()
        new = e03.has_turn(nodes, s) and texts_digest(nodes, s) != before
        paused = ui.shows(nodes, s.VOICE_MIC_PAUSED)
        if paused:
            seen["paused_seen"] = True
            seen["text_first"] &= new
            seen["level_zero"] &= level(nodes) == 0
        if not spoken_turn:
            return new
        return new and not paused and len(spoken(e15.log_since(ctx, offset))) > count

    thread = play_async(path)
    try:
        ui.wait(probe, ui.MODEL_TIMEOUT_S)
    except TimeoutError:
        return None
    finally:
        thread.join()
    texts = e03.view(app.nodes(), s)["texts"]
    if texts is not None:
        e03._remember(ctx, texts)
    return seen


def measure(action: Callable[[], None], done: Callable[[], Any]) -> float | None:
    """Record the cable while ``action`` runs until ``done``: speech seconds, else None."""
    recorder = audio.CableRecorder().start()
    try:
        action()
        ui.wait(done, ui.MODEL_TIMEOUT_S)
    except TimeoutError:
        return None
    finally:
        rate, samples = recorder.stop()
    span = audio.speech_span(samples, rate)
    return round(span[1] - span[0], 3) if span else None


def readiness(app: Any, s: Any) -> str:
    """The Settings › Diagnostics readiness text (the value of the element named
    "Readiness", read through every pattern UIA offers for a selectable label)."""
    parts: list[str] = []
    for node in app.nodes():
        if node.visible and node.name == s.DIAG_READINESS:
            parts += [*node.texts(), *_pattern_texts(node.handle)]
    return "\n".join(parts)


def _pattern_texts(handle: Any) -> list[str]:
    if handle is None:
        return []
    reads = (
        lambda: handle.iface_text.DocumentRange.GetText(-1),
        lambda: handle.legacy_properties().get("Value"),
        lambda: handle.window_text(),
    )
    return [str(text) for text in (uia._quiet(read) for read in reads) if text]


def readiness_row(s: Any, language: str, status: str) -> str:
    item = s.VOICE_READINESS_ROW.format(language=name(language))
    return s.DIAG_READINESS_ROW.format(item=item, status=status)


def settings_rate(ctx: Any, language: str) -> float | None:
    """``tts.output[language].rate`` of the local settings file, if any."""
    try:
        data = json.loads(ctx.local_settings.read_text(encoding="utf-8"))
        return float(data["tts"]["output"][language]["rate"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def open_options(app: Any, s: Any, language: str) -> list[Node] | None:
    """Press **Voice options…** of ``language``; the dialog's nodes once it has loaded."""
    title = s.VOICE_OPTIONS_TITLE.format(language=name(language))
    button = ui.find(app.nodes(), s.VOICE_OPTIONS_NAME.format(language=name(language)))
    if button is None or not button.enabled:
        return None
    app.press(button)

    def loaded() -> list[Node] | None:
        nodes = app.window_nodes(title)
        return nodes if nodes and not ui.shows(nodes, s.VOICE_LOADING) else None

    try:
        return ui.wait(loaded, ui.MODEL_TIMEOUT_S)
    except TimeoutError:
        return None


def controls(nodes: list[Node], s: Any) -> list[str]:
    """Which of Voice, Rate and Volume the dialog shows (in that order)."""
    shown = [
        (ui.find(nodes, s.VOICE_CHOICE, "ComboBox"), "voice"),
        (ui.find(nodes, s.VOICE_RATE, "Slider"), "rate"),
        (ui.find(nodes, s.VOICE_VOLUME, "Slider"), "volume"),
    ]
    return [label for node, label in shown if node is not None]


def close_options(app: Any, s: Any, language: str) -> bool:
    title = s.VOICE_OPTIONS_TITLE.format(language=name(language))
    button = ui.find(app.window_nodes(title) or (), s.VOICE_CLOSE, "Button")
    if button is None:
        return False
    app.press(button)
    try:
        ui.wait(lambda: app.window_nodes(title) is None)
    except TimeoutError:
        return False
    return True
