"""Conversation Stop and state truthfulness (session-status-truthfulness WI-02, AC-07..AC-12).

An offscreen ``MainWindow`` over spy adapters. Hung workers are spies that block until the
test releases them; bounds are shortened through ``SessionController.flush_timeout``, so no
test waits for the real 10 s. Code evidence only, not native Windows product evidence.
"""

from __future__ import annotations

import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import itertools

from lianiq.pipeline import PipelineEvent, PipelineEventKind
from lianiq.ui import notice_catalog as catalog
from lianiq.ui import strings
from lianiq.ui import strings_session as S
from lianiq.ui.shell.session_owner import SessionState
from lianiq.ui.shell.workspaces import WorkspaceId
from tests._spy_window import spies  # noqa: F401
from tests.ui._language_helpers import (
    click,
    language_window,  # noqa: F401
    start,
    submit,
    transcript,
    wait_until,
)

CONVERSATION = WorkspaceId.CONVERSATION
ERROR_KEY = catalog.error_key(CONVERSATION)


class Gate:
    """A translator spy that blocks every call until ``release`` (or the bound expires)."""

    def __init__(self, translator) -> None:
        self.translate = translator.translate
        self.entered = threading.Event()
        self.released = threading.Event()
        translator.translate = self

    def __call__(self, text, edge, context=()):
        self.entered.set()
        assert self.released.wait(timeout=5.0)
        return self.translate(text, edge, context)


def idle(window) -> bool:
    return window.session_owner.state is SessionState.IDLE


def test_ac07_stop_is_acknowledged_at_once_and_the_gui_keeps_running(window, spies) -> None:  # noqa: F811
    from PySide6.QtCore import QTimer

    start(window)
    gate = Gate(spies.translator)
    submit(window, spies, transcript("Guten Tag", "de"))  # in translation
    assert wait_until(gate.entered.is_set)
    submit(window, spies, transcript("Wie geht es", "de"))  # queued
    ticks: list[float] = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start(50)
    threading.Timer(0.4, gate.released.set).start()  # the drain ends within the bound

    began = time.monotonic()
    window.stop_active_session()  # F9
    acknowledged = time.monotonic() - began

    assert acknowledged < 0.1
    assert window.state_label.text() == S.STATE_STOPPING
    assert not window.capture.running and window.level_bar.value() == 0
    assert window.session_owner.state is SessionState.STOPPING
    assert wait_until(lambda: idle(window))
    timer.stop()
    assert len(ticks) >= 5  # the 50 ms timer fired while the turns drained
    gaps = [later - earlier for earlier, later in itertools.pairwise(ticks)]
    assert max(gaps) < 0.2
    assert window.state_label.text() == S.counted(S.STATE_STOPPED, 2) == "Stopped · 2 turns kept"
    assert len(window.history) == 2  # the queued turn was translated within the bound


def test_ac08_a_hung_translation_times_out_and_the_next_start_waits_for_it(
    window,
    spies,  # noqa: F811
) -> None:
    start(window)
    window.conversation.session_controller.flush_timeout = 0.3
    gate = Gate(spies.translator)
    submit(window, spies, transcript("Guten Tag", "de"))
    assert wait_until(gate.entered.is_set)

    window.stop_active_session()

    assert wait_until(lambda: idle(window))
    assert window.state_label.text() == "Stopped — 1 not finished"
    assert window.notices.get(catalog.STOP_TIMEOUT_KEY) is not None
    assert window.session_owner.lingering() is CONVERSATION
    click(window.start_button)  # refused while the worker is alive (AC-05)
    assert window.notices.get(catalog.STILL_FINISHING_KEY) is not None
    assert not window.capture.running and idle(window)

    gate.released.set()  # the spy returns: its late result is never shown
    assert wait_until(lambda: not window.runner.alive())
    wait_until(lambda: False, 200)
    assert window.history == () and len(window.conversation.turns) == 0
    assert window.session_owner.lingering() is None
    start(window)  # works again without other action
    assert window.notices.get(catalog.STILL_FINISHING_KEY) is None


def test_ac09_late_signals_of_an_ended_session_change_nothing(window, spies) -> None:  # noqa: F811
    start(window)
    submit(window, spies, transcript("Guten Tag", "de"))
    assert wait_until(lambda: len(window.history) == 1)
    old = window.conversation._generation
    window.stop_active_session()
    assert wait_until(lambda: idle(window))
    result = window.history[0]
    label = window.state_label.text()
    live = {notice.key for notice in window.notices.live()}

    # Stopped: the worker's callbacks now carry no live generation.
    runner = window.runner
    runner.on_result(result)
    runner.on_busy(True)
    runner.on_error("late failure")
    runner.on_event(PipelineEvent(PipelineEventKind.TURNS_DROPPED, count=1))
    wait_until(lambda: False, 100)
    assert len(window.history) == 1 and window.state_label.text() == label

    # Stopped and started again: the earlier session's generation is dropped.
    start(window)
    bridge = window.bridge
    bridge.result.emit(result, old)
    bridge.busy.emit(True, old)
    bridge.held.emit(object(), old)
    bridge.held_resolved.emit(old)
    bridge.error.emit("late failure", old)
    bridge.playback_state.emit("playing", old)
    bridge.pipeline_event.emit(PipelineEvent(PipelineEventKind.QUEUE_OVERFLOW), old)
    wait_until(lambda: False, 100)
    assert len(window.history) == 1
    assert window.state_label.text() == "Listening …"
    assert not window.held_turn_bar.isVisible()
    assert {notice.key for notice in window.notices.live()} <= live


def test_ac10_a_failed_turn_keeps_the_error_until_its_notice_is_closed(window, spies) -> None:  # noqa: F811
    start(window)

    def fail(*_args, **_kwargs):
        raise RuntimeError("translation failed")

    spies.translator.translate = fail
    submit(window, spies, transcript("Guten Tag", "de"))  # on_error, then on_busy(False)

    assert wait_until(lambda: window.notices.get(ERROR_KEY) is not None)
    wait_until(lambda: False, 100)
    assert window.state_label.text() == S.STATE_ERROR
    generation = window.conversation._generation
    window.bridge.busy.emit(False, generation)
    window.bridge.playback_state.emit("idle", generation)
    window.conversation.refresh_availability()
    wait_until(lambda: False, 50)
    assert window.state_label.text() == S.STATE_ERROR

    window.notices.resolve(ERROR_KEY)  # the user closes the notice

    assert window.state_label.text() == "Listening …"


def test_ac06_listening_is_never_shown_while_muted(window, spies) -> None:  # noqa: F811
    start(window)
    generation = window.conversation._generation
    window.bridge.playback_state.emit("playing", generation)
    window.bridge.busy.emit(False, generation)
    wait_until(lambda: False, 50)
    assert window.state_label.text() == strings.VOICE_MIC_PAUSED
    window.bridge.playback_state.emit("idle", generation)
    assert wait_until(lambda: window.state_label.text() == "Listening …")


def test_ac11_lost_turn_notices_survive_start_and_say_how_to_repeat(window, spies) -> None:  # noqa: F811
    where = window.conversation.notices.where()
    lost = [
        catalog.turns_dropped(1, where),
        catalog.queue_overflow(where),
        catalog.held_discarded(1, where),
        catalog.synthesis_failed("German", where),
    ]
    for notice in lost:
        window.post_notice(notice)
    assert lost[0].detail == S.DETAIL_TURNS_DROPPED
    window.post_notice(catalog.model_failed(CONVERSATION, "boom", where, lambda: None))
    spies.release_warm_up.clear()  # models load until released

    click(window.start_button)

    assert wait_until(lambda: window.conversation.starting)
    assert window.notices.get(catalog.model_failed_key(CONVERSATION)) is not None
    spies.release_warm_up.set()
    assert wait_until(lambda: window.capture.running)
    assert window.notices.get(catalog.model_failed_key(CONVERSATION)) is None
    assert all(window.notices.get(notice.key) is not None for notice in lost)


def test_ac12_ready_on_launch_and_stopped_with_the_turns_kept(window, spies) -> None:  # noqa: F811
    assert window.state_label.text() == "Ready"
    start(window)
    submit(window, spies, transcript("Guten Tag", "de"))
    submit(window, spies, transcript("Wie geht es", "de"))
    assert wait_until(lambda: len(window.history) == 2)

    window.stop_active_session()

    assert wait_until(lambda: idle(window))
    assert window.state_label.text() == "Stopped · 2 turns kept"
    assert len(window.history) == 2
    window.conversation.refresh_availability()
    assert window.state_label.text() == "Stopped · 2 turns kept"


def test_a_stop_that_raises_ends_the_session_and_says_so(window, spies, monkeypatch) -> None:  # noqa: F811
    start(window)

    def broken():
        raise RuntimeError("stop failed")

    monkeypatch.setattr(window.conversation.session_controller, "stop", broken)
    window.stop_active_session()

    assert wait_until(lambda: idle(window))
    assert window.notices.get(catalog.STOP_FAILED_KEY) is not None
    assert window.state_label.text() == "Stopped · 0 turns kept"
