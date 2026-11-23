"""Unit tests of the E-03 VoR-02 path, its stable reads and masks, and the E-10 notice read.

E-03 selects "CABLE Output" as Microphone in Settings (only ``name_matches`` is stored) and
turns every voice switch off before Start; it records the turn only once the view is stable, needs
a readable scroll value and an unchanged pair and direction, and masks both transcript
panels and every element showing transcript text in its screenshots. E-10 reads only the
notice elements, never the notice history that logs every posted notice title (CAP-0174
contract §5, §7.2, AC-11).
"""

from __future__ import annotations

import json

import pytest

from native_e2e import screens
from native_e2e.evidence.model import Status
from native_e2e.rows import e01, e03, e10, ui
from native_e2e.uia import Node
from tests._native_fake_app import (
    CABLE,
    PANEL_RECTS,
    TRANSLATION,
    VOICE_SWITCHES,
    FakeApp,
    install,
    make_ctx,
)
from tests.test_native_screens import NAMES, black_inside


@pytest.fixture
def ctx(tmp_path):
    return make_ctx(tmp_path)


def failed(row) -> list[str]:
    return [check.name for check in row.checks if check.result is not Status.PASS]


def run_e03(ctx, monkeypatch, app=None, **knobs):
    app = app or FakeApp(**knobs)
    install(monkeypatch, app)
    return e03.run(ctx), app


# E-03: the VoR-02 path before Start ----------------------------------------------------------


def test_e03_selects_the_cable_and_turns_voice_output_off_before_start(ctx, monkeypatch) -> None:
    row, app = run_e03(ctx, monkeypatch)
    assert row.status is Status.PASS, row.checks
    names = [check.name for check in row.checks]
    assert names[:4] == [
        "test-phrase-sha256",
        "microphone-cable-selected",
        "voice-output-off",
        "session-running",
    ]
    details = {check.name: check.detail for check in row.checks}
    assert details["microphone-cable-selected"] == "name_matches: true"
    assert app.mic == CABLE and not any(app.voices.values())
    assert "CABLE" not in json.dumps(row.to_dict(), ensure_ascii=False)  # never the name


def test_e03_keeps_voice_output_off_when_it_is_already_off(ctx, monkeypatch) -> None:
    app = FakeApp()
    app.voices = dict.fromkeys(VOICE_SWITCHES, False)
    row, _ = run_e03(ctx, monkeypatch, app)
    assert row.status is Status.PASS, row.checks
    assert not any(app.voices.values())


def test_e03_turns_off_only_the_switch_that_is_on(ctx, monkeypatch) -> None:
    app = FakeApp()
    app.voices[VOICE_SWITCHES[0]] = False
    row, _ = run_e03(ctx, monkeypatch, app)
    assert row.status is Status.PASS, row.checks
    assert app.voices == dict.fromkeys(VOICE_SWITCHES, False)


@pytest.mark.parametrize(
    ("knobs", "check", "detail"),
    [
        ({"no_cable_item": True}, "microphone-cable-selected", "name_matches: false"),
        ({"mic_ignored": True}, "microphone-cable-selected", "name_matches: false"),
        ({"missing": {"Microphone"}}, "microphone-cable-selected", "name_matches: false"),
        ({"voice_stuck": True}, "voice-output-off", "timeout"),
        ({"missing": set(VOICE_SWITCHES)}, "voice-output-off", "not-found"),
    ],
)
def test_e03_never_starts_unless_the_cable_and_voice_output_are_set(
    ctx, monkeypatch, knobs, check, detail
) -> None:
    row, app = run_e03(ctx, monkeypatch, **knobs)
    assert failed(row) == [check]
    assert {c.name: c.detail for c in row.checks}[check] == detail
    assert "session-running" not in [c.name for c in row.checks] and not app.running


def test_e03_fails_when_the_cable_name_is_unknown(ctx, monkeypatch) -> None:
    app = FakeApp()
    install(monkeypatch, app)
    from native_e2e import audio

    monkeypatch.setattr(audio, "wasapi_name", lambda prefix, kind: None)
    row = e03.run(ctx)
    assert failed(row) == ["microphone-cable-selected"]


# E-03: stable reads after F9 ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("knobs", "check"),
    [
        ({"no_scroll": True}, "scroll-unchanged"),
        ({"scroll": True}, "scroll-unchanged"),
        ({"pair": True}, "pair-unchanged"),
        ({"missing": {"Language pair"}}, "pair-unchanged"),
        ({"direction": True}, "direction-unchanged"),
        ({"missing": {"Conversation direction"}}, "direction-unchanged"),
    ],
)
def test_e03_fails_on_unreadable_or_changed_scroll_pair_or_direction(
    ctx, monkeypatch, knobs, check
) -> None:
    row, _ = run_e03(ctx, monkeypatch, **knobs)
    assert failed(row) == [check]


class GrowingApp(FakeApp):
    """The translation still grows for a few reads after the turn first appears."""

    def __init__(self, **knobs) -> None:
        super().__init__(**knobs)
        self.pending = 0

    def hear_phrase(self) -> None:
        super().hear_phrase()
        self.translation = self.translation[:4]
        self.pending = 3

    def nodes(self):
        if self.pending:
            self.pending -= 1
            self.translation = TRANSLATION[: len(self.translation) + 3]
            if not self.pending:
                self.translation = TRANSLATION
        return super().nodes()


def test_e03_records_the_transcript_only_once_the_view_is_stable(ctx, monkeypatch) -> None:
    row, _ = run_e03(ctx, monkeypatch, GrowingApp())
    assert row.status is Status.PASS, row.checks
    assert ctx.state["transcripts"][1] == TRANSLATION


def test_e03_adds_the_label_stripped_transcript_to_the_scan_secrets(ctx, monkeypatch) -> None:
    row, _ = run_e03(ctx, monkeypatch)
    assert row.status is Status.PASS, row.checks
    for needle in e10.transcript_needles(ctx.state["transcripts"]):
        assert needle in ctx.secrets
    assert "早上好，这是一个测试。" in ctx.secrets


# E-03: transcript panels are masked in every screenshot --------------------------------------


def test_e03_screenshots_mask_both_transcript_panels(ctx, monkeypatch) -> None:
    row, _ = run_e03(ctx, monkeypatch)
    assert row.status is Status.PASS, row.checks
    for name in ("e03-running.png", "e03-after.png"):
        png = (ctx.out / "screens" / name).read_bytes()
        assert black_inside(png, PANEL_RECTS, (100, 100)), name


def test_mask_rects_mask_the_transcript_panels_whatever_their_text() -> None:
    nodes = [
        Node("Original", "Edit", value="", rect=(0, 0, 5, 5)),
        Node("Translation", "Document", value="Hallo", rect=(0, 10, 5, 15)),
        Node("Original", "Text", rect=(0, 20, 5, 25)),  # the heading label
    ]
    assert screens.mask_rects(nodes, NAMES) == [(0, 0, 5, 5), (0, 10, 5, 15)]


def test_a_screenshot_masks_every_element_showing_transcript_text(ctx, monkeypatch) -> None:
    tip = Node("Last turn", "Text", description="Guten Morgen, das ist ein Test.",
               rect=(150, 150, 250, 180))  # fmt: skip
    app = FakeApp(extra=[tip])
    install(monkeypatch, app)
    ctx.state["transcripts"] = ["German: Guten Morgen, das ist ein Test."]
    check, artifact = ui.screenshot(ctx, app, "screens/t.png", "screenshot-masked")
    png = (ctx.out / artifact.path).read_bytes()
    assert black_inside(png, [tip.rect, *PANEL_RECTS], (100, 100))
    assert check.detail == "masked=3"


# E-10: only the notice elements count, not the notice history ---------------------------------


def run_e10_after_e03(ctx, monkeypatch, **knobs):
    row, app = run_e03(ctx, monkeypatch, **knobs)
    assert row.status is Status.PASS, row.checks
    return e10.run(ctx), app


def test_e10_passes_although_the_history_logs_the_saved_notice(ctx, monkeypatch) -> None:
    row, app = run_e10_after_e03(ctx, monkeypatch)
    assert "settings.export-result: Diagnostics saved as" in app.log  # as in the real app
    assert row.status is Status.PASS, row.checks
    details = {check.name: check.detail for check in row.checks}
    assert details["failure-notice-shown"] == "dialog-closed: true"


def test_e10_dismisses_a_dialog_left_open_before_the_screenshot_and_close(ctx, monkeypatch):
    row, app = run_e10_after_e03(ctx, monkeypatch, dialog_stuck=True)
    assert "failure-notice-shown" in failed(row)
    assert {c.name: c.detail for c in row.checks}["failure-notice-shown"] == (
        "dialog-closed: false"
    )
    assert app.closed and app.dialog_at_close is False


class _BrokenUia(FakeApp):
    def window_nodes(self, title):
        if self.dialog:
            raise RuntimeError("uia error")
        return super().window_nodes(title)


def test_e10_closes_the_app_when_the_dialog_check_raises(ctx, monkeypatch) -> None:
    app = _BrokenUia()
    install(monkeypatch, app)
    with pytest.raises(RuntimeError, match="uia error"):
        e10.run(ctx)
    assert app.closed


def test_e10_needs_the_failure_in_a_notice_not_only_in_the_history(ctx, monkeypatch) -> None:
    app = FakeApp()
    install(monkeypatch, app)
    original = app.post

    def history_only(title, key, severity="info"):
        original(title, key, severity)
        if key == "settings.export-failed":
            app.notices.pop()

    app.post = history_only
    row = e10.run(ctx)
    assert "failure-notice-shown" in failed(row)


# E-01: no process inspected is not a pass ------------------------------------------------------


def test_e01_fails_when_no_app_process_was_inspected(ctx, monkeypatch) -> None:
    app = FakeApp(no_processes=True)
    install(monkeypatch, app)
    row = e01.run(ctx)
    assert failed(row) == ["no-model-file-open-before-start"]
