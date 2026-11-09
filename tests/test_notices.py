"""Notices (CAP-0168 WI-03; contract.md §3, spec §2.3.4): Qt-free unit tests.

AC-23: a blocking notice stays until its own ``resolve``; repeats of a key are one notice;
an older generation is dropped. AC-24 (Unit): every mapped failure is exactly one notice
that names what failed, the mode/lane/language, whether recording/playback continues and its
action. The ``pipeline.py`` notice events (overflow, dropped turns, playback failure) are in
``test_notices_pipeline_events.py``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from lianiq.ui import notice_catalog as catalog
from lianiq.ui import strings
from lianiq.ui.notices import Notice, NoticeAction, NoticeCenter, Severity
from lianiq.ui.shell.workspaces import WorkspaceId

CONVERSATION, CALL_BRIDGE, SETTINGS = (
    WorkspaceId.CONVERSATION,
    WorkspaceId.CALL_BRIDGE,
    WorkspaceId.SETTINGS,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 1.0
        return self.now


def notice(key="k", severity=Severity.BLOCKING, title="T", workspace=CONVERSATION, **kw) -> Notice:
    return Notice(
        key, severity, title, "detail", "Conversation", "Recording stopped.", workspace, **kw
    )


@pytest.fixture
def center() -> NoticeCenter:
    return NoticeCenter(clock=FakeClock())


# AC-23 ------------------------------------------------------------------------------------


def test_ac23_a_blocking_notice_survives_unrelated_success_and_later_info(center) -> None:
    assert center.post(notice("mic", title="Microphone lost"))
    # Unrelated work succeeds: other notices come and go, an info notice arrives.
    center.post(notice("other", Severity.WARNING))
    center.resolve("other")
    center.resolve("never-posted")
    assert center.post(notice("saved", Severity.INFO, title="Saved"))
    assert center.top(CONVERSATION).title == "Microphone lost"

    # An info or warning post with the blocking key is refused and changes nothing.
    assert not center.post(notice("mic", Severity.INFO, title="All good"))
    assert not center.post(notice("mic", Severity.WARNING, title="Better"))
    assert center.get("mic").title == "Microphone lost"
    assert center.get("mic").severity is Severity.BLOCKING

    center.resolve("mic")  # only its own resolution clears it
    assert center.get("mic") is None
    assert center.top(CONVERSATION).title == "Saved"


def test_ac23_repeated_posts_of_one_key_are_one_notice_with_a_repeat_count(center) -> None:
    for title in ("first", "second", "third"):
        assert center.post(notice("queue", Severity.WARNING, title=title))
    assert center.count(CONVERSATION) == 1
    live = center.top(CONVERSATION)
    assert (live.title, live.repeats) == ("third", 2)
    assert len(center.history()) == 3  # the history keeps each accepted post


def test_ac23_a_notice_of_an_older_generation_is_dropped(center) -> None:
    assert not center.post(notice("late", generation=3), current_generation=4)
    assert center.get("late") is None and center.history() == ()
    assert center.post(notice("same", generation=4), current_generation=4)
    assert center.post(notice("none"), current_generation=4)  # no generation: accepted
    assert center.post(notice("newer", generation=5), current_generation=4)
    assert {item.key for item in center.live()} == {"same", "none", "newer"}


def test_top_is_the_highest_severity_then_the_newest_per_workspace(center) -> None:
    center.post(notice("info", Severity.INFO))
    center.post(notice("old-block", Severity.BLOCKING))
    center.post(notice("warn", Severity.WARNING))
    center.post(notice("new-block", Severity.BLOCKING))
    center.post(notice("bridge", Severity.BLOCKING, workspace=CALL_BRIDGE))
    assert [n.key for n in center.live(CONVERSATION)] == ["new-block", "old-block", "warn", "info"]
    assert center.top(CALL_BRIDGE).key == "bridge"
    assert (center.count(CONVERSATION), center.count(SETTINGS)) == (4, 0)
    center.post(notice("old-block", Severity.BLOCKING))  # a repeat makes it the newest
    assert center.top(CONVERSATION).key == "old-block"


def test_listeners_see_posts_and_resolutions(center) -> None:
    seen = []
    center.subscribe(lambda change, item: seen.append((change, item.key)))
    center.post(notice("a"))
    center.post(notice("a", generation=1), current_generation=2)  # dropped: no event
    center.resolve("a")
    center.resolve("a")  # already resolved: no event
    assert seen == [("posted", "a"), ("resolved", "a")]


def test_action_availability_follows_its_predicate() -> None:
    state = {"open": True}
    action = NoticeAction("Reconnect", lambda: None, enabled=lambda: not state["open"])
    assert not action.available()
    state["open"] = False
    assert action.available()
    assert NoticeAction("Retry", lambda: None).available()


def test_notices_catalog_and_diagnostics_are_qt_free() -> None:
    code = (
        "import sys, lianiq.ui.notices, lianiq.ui.notice_catalog, lianiq.diagnostics; "
        "assert 'PySide6' not in sys.modules, 'PySide6 imported'"
    )
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "-c", code], cwd=root, capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr


# AC-24 (Unit): one notice per mapped §2.3.4 failure ---------------------------------------


def nothing() -> None:
    return None


def mapped_cases() -> dict[str, Notice]:
    pair = "Conversation · German ↔ Mandarin (Simplified)"
    lane = "Call Bridge · outbound · German"
    return {
        "mode unavailable": catalog.mode_unavailable(
            CONVERSATION, "Not available: missing voice German", pair, nothing
        ),
        "pair locked": catalog.pair_locked(pair),
        "direction unavailable": catalog.direction_unavailable(
            "Not available: missing translation Mandarin (Simplified) → German", pair
        ),
        "model preparation failed": catalog.model_failed(CONVERSATION, "disk", pair, nothing),
        "start failed": catalog.start_failed(CONVERSATION, "device busy", pair, nothing),
        "held turns discarded": catalog.held_discarded(1, pair),
        "queue overload": catalog.queue_overflow(pair),
        "dropped turns": catalog.turns_dropped(2, pair),
        "missing voice": catalog.voice_missing("Not available: missing voice German", pair),
        "session busy": catalog.session_busy(CALL_BRIDGE, CONVERSATION),
        "microphone lost": catalog.microphone_lost("Headset", pair, nothing, None, nothing),
        "speakers lost": catalog.speakers_lost("Headset", pair, nothing, None, nothing),
        "device unavailable": catalog.device_unavailable("Microphone", "Headset", pair, nothing),
        "device unusable": catalog.device_unavailable(
            "Speakers", "Hdmi", pair, nothing, reason="This device has no usable output channels"
        ),
        "no signal": catalog.no_signal("Headset", pair, nothing),
        "devices changed": catalog.devices_changed("added 'Headset'", pair),
        "export failed": catalog.export_failed(SETTINGS, "Permission denied", "Settings", nothing),
        "bridge error": catalog.bridge_failed("outbound", "playback_failure", lane),
        "bridge dropped": catalog.bridge_dropped("stale", lane),
        "bridge capture muted": catalog.bridge_capture_muted("stream error", lane),
        "bridge recovery failed": catalog.bridge_recovery_failed("registry", lane),
    }


@pytest.mark.parametrize("case", sorted(mapped_cases()))
def test_ac24_each_mapped_failure_names_what_where_continues_and_action(case) -> None:
    item = mapped_cases()[case]
    assert item.title.strip(), "what failed"
    workspace_label = {CONVERSATION: "Conversation", CALL_BRIDGE: "Call Bridge"}
    assert item.source.startswith(workspace_label.get(item.workspace, "Settings"))
    assert any(word in item.continues for word in ("Recording", "recording", "session", "lane"))
    # An action, or a next step that says what to do (or that none is needed).
    assert item.actions or item.detail.strip()
    for action in item.actions:
        assert action.label in {
            strings.NOTICE_RETRY,
            strings.DEVICE_RECONNECT,
            strings.DEVICE_CHOOSE,
        }


def test_ac24_every_mapped_failure_is_exactly_one_notice(center) -> None:
    cases = mapped_cases()
    for item in cases.values():
        assert center.post(item)
    for item in cases.values():  # the same failure again: still one notice each
        center.post(item)
    assert len(center.live()) == len(cases)


def test_ac24_device_notices_use_the_contract_keys_and_actions() -> None:
    can = {"reconnect": False}
    lost = catalog.speakers_lost(
        "USB Headset", "Conversation", nothing, lambda: can["reconnect"], nothing
    )
    assert lost.title == (
        "Speakers 'USB Headset' disconnected. Spoken output stopped; translations still appear "
        "as text."
    )
    assert lost.continues == "Recording continues. Spoken output stopped."
    reconnect, choose = lost.actions
    assert (reconnect.label, choose.label) == ("Reconnect", "Choose device")
    assert not reconnect.available() and reconnect.disabled_hint == "Available after Stop"
    can["reconnect"] = True
    assert reconnect.available()
    mic = catalog.microphone_lost("USB Headset", "Conversation", nothing, None, nothing)
    assert mic.title.startswith("Microphone 'USB Headset' disconnected. Recording stopped.")
    assert mic.severity is Severity.BLOCKING and mic.key == catalog.MICROPHONE_LOST


def test_ac24_bridge_errors_name_the_lane_and_language() -> None:
    item = catalog.bridge_failed(
        "inbound", "recognition_failure", "Call Bridge · inbound · Mandarin"
    )
    assert item.title == "Call Bridge inbound lane failed closed: recognition_failure"
    assert "inbound" in item.source and "Mandarin" in item.source
    assert item.continues == "This lane is muted; the other lane continues."
    unknown = catalog.bridge_failed(None, "route_test_failed", "Call Bridge")
    assert unknown.title == "Call Bridge lane failed closed: route_test_failed"
