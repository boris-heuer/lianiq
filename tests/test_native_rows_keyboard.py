"""Unit tests of the keyboard rows E-31, E-32 and E-33 with a keyboard-driven fake window.

Each row passes when every Tab stop is named and the keys act as the plan rows say; one knob
per test breaks one behaviour and the named check fails. No row confirms a dialog: the fake
records a pressed **Yes** (removal) and the rows never press one.
"""

from __future__ import annotations

import json

import pytest

from native_e2e import uia_app
from native_e2e.evidence.model import Method, Status
from native_e2e.rows import e31, e32, e33, keys, ui
from native_e2e.uia import Node
from tests._native_fake_app import install, make_ctx
from tests._native_keyboard_app import MODELS, KeyApp


@pytest.fixture
def ctx(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.state["settings_backup"] = {"existed": False}
    return ctx


def run_row(module, ctx, monkeypatch, **knobs):
    app = KeyApp(**knobs)
    install(monkeypatch, app)
    monkeypatch.setattr(ui, "FOCUS_MOVE_S", 0.02)
    monkeypatch.setattr(e33, "_models", lambda: list(MODELS))
    return module.run(ctx), app


def failed(row) -> list[str]:
    return [check.name for check in row.checks if check.result is not Status.PASS]


def test_e31_passes_when_every_stop_is_named_and_the_keys_work(ctx, monkeypatch) -> None:
    row, app = run_row(e31, ctx, monkeypatch)
    assert row.status is Status.PASS, row.checks
    assert row.acs == ("AC-28", "AC-22") and row.method is Method.NATIVE
    assert [check.name for check in row.checks] == [
        "conversation-tab-stops-named",
        "space-toggles-voice-switch",
        "enter-opens-voice-options",
        "voice-options-tab-stops-named",
        "escape-closes-voice-options",
        "settings-tab-stops-named",
        "space-opens-export-dialog",
        "escape-closes-export-dialog",
        "focus-returns-to-export",
        "ctrl-1-7-switch-pages",
        "settings-baseline-restored",
    ]
    assert app.voices["Speak German"] is True and app.dialog is None and app.closed
    assert row.checks[0].detail == "stops=11"  # seven entries, two switches, two buttons
    assert row.checks[-2].detail == "switched=7/7" and app.page == "Conversation"


@pytest.mark.parametrize(
    ("knobs", "name"),
    [
        ({"unnamed": "Conversation"}, "conversation-tab-stops-named"),
        ({"unnamed": "Settings"}, "settings-tab-stops-named"),
        ({"space_ignored": True}, "space-toggles-voice-switch"),
        ({"escape_ignored": True}, "escape-closes-voice-options"),
        ({"ctrl_ignored": "5"}, "ctrl-1-7-switch-pages"),
    ],
)
def test_e31_fails_when_a_pass_rule_does_not_hold(ctx, monkeypatch, knobs, name) -> None:
    row, app = run_row(e31, ctx, monkeypatch, **knobs)
    assert row.status is Status.FAIL and name in failed(row)
    assert app.closed


def test_e31_walks_the_options_dialog_with_space_when_enter_does_not_open_it(
    ctx, monkeypatch
) -> None:
    row, _app = run_row(e31, ctx, monkeypatch, enter_ignored=True)
    assert failed(row) == ["enter-opens-voice-options"]
    names = [check.name for check in row.checks]
    assert "space-opens-voice-options" in names and "voice-options-tab-stops-named" in names


def test_e31_records_the_control_types_of_unnamed_stops_only(ctx, monkeypatch) -> None:
    row, _app = run_row(e31, ctx, monkeypatch, unnamed="Conversation")
    assert row.checks[0].detail == "stops=12 unnamed=Button"


def test_e32_passes_with_f8_f9_ctrl_enter_tab_enter_and_escape(ctx, monkeypatch) -> None:
    row, app = run_row(e32, ctx, monkeypatch)
    assert row.status is Status.PASS, row.checks
    assert row.acs == ("AC-30", "AC-19", "AC-36") and row.method is Method.VIRTUAL_DEVICE
    names = [check.name for check in row.checks]
    assert names[names.index("listen-tab-stops-named") :] == [
        "listen-tab-stops-named",
        "f8-starts-listening",
        "f9-stops-listening",
        "fixture-typed",
        "ctrl-enter-translates",
        "tab-leaves-source-text",
        "tab-leaves-translation",
        "text-tab-stops-named",
        "enter-on-focused-button",
        "focused-button-named-cancel",
        "escape-cancels-translation",
        "focused-button-named-translate",
        "settings-baseline-restored",
    ]
    assert app.source == e32.LONG and not app.translating and app.closed
    text = json.dumps(row.to_dict(), ensure_ascii=False)
    assert "Guten Morgen" not in text and "早上好" not in text
    assert any("Guten Morgen" in secret for secret in ctx.secrets)


@pytest.mark.parametrize(
    ("knobs", "name"),
    [
        ({"unnamed": "Listen & translate"}, "listen-tab-stops-named"),
        ({"f8_ignored": True}, "f8-starts-listening"),
        ({"unnamed": "Text translation"}, "text-tab-stops-named"),
        ({"fast": True}, "enter-on-focused-button"),
    ],
)
def test_e32_fails_when_a_pass_rule_does_not_hold(ctx, monkeypatch, knobs, name) -> None:
    row, app = run_row(e32, ctx, monkeypatch, **knobs)
    assert row.status is Status.FAIL and name in failed(row)
    assert app.closed


def test_e33_passes_and_never_confirms_a_dialog(ctx, monkeypatch) -> None:
    row, app = run_row(e33, ctx, monkeypatch)
    assert row.status is Status.PASS, row.checks
    assert row.acs == ("AC-26",)
    assert [check.name for check in row.checks] == [
        "pack-states-shown",
        "packs-tab-stops-named",
        "pack-actions-shown",
        "space-opens-assistant",
        "assistant-tab-stops-named",
        "escape-closes-assistant",
        "space-opens-details",
        "details-tab-stops-named",
        "escape-closes-details",
        "space-opens-remove",
        "remove-tab-stops-named",
        "escape-closes-remove",
        "packs-unchanged-after-escape",
        "settings-baseline-restored",
    ]
    assert row.checks[2].detail == "update=0 redownload=0 remove=1 custom_path=0"
    assert not app.removed and not app.downloaded and app.closed


@pytest.mark.parametrize("knob", ["no_get", "no_remove"])
def test_e33_is_blocked_with_a_named_reason_without_the_action(ctx, monkeypatch, knob) -> None:
    row, _app = run_row(e33, ctx, monkeypatch, **{knob: True})
    reason = {"no_get": "no-details-action", "no_remove": "no-remove-action"}[knob]
    assert row.status is Status.BLOCKED and row.reason == reason


@pytest.mark.parametrize(
    ("knobs", "name"),
    [
        ({"checking": True}, "pack-states-shown"),
        ({"unnamed": "Language packs"}, "packs-tab-stops-named"),
        ({"escape_ignored": True}, "escape-closes-assistant"),
    ],
)
def test_e33_fails_when_a_pass_rule_does_not_hold(ctx, monkeypatch, knobs, name) -> None:
    row, app = run_row(e33, ctx, monkeypatch, **knobs)
    assert row.status is Status.FAIL and name in failed(row) and row.reason == "keyboard"
    assert not app.removed


def test_walk_fails_an_open_cycle_and_tab_to_gives_up_after_max_stops(monkeypatch) -> None:
    monkeypatch.setattr(ui, "FOCUS_MOVE_S", 0.02)
    app = KeyApp()
    assert keys.walk(app, "x", max_stops=3).detail == "stops=3 cycle-open"
    assert keys.tab_to(app, keys.named("missing"), max_stops=3) is None
    assert keys.named("Translation")(Node("Translation", "Text")) is False


def test_dialog_keys_do_not_focus_the_main_window(monkeypatch) -> None:
    sent: list[str] = []
    monkeypatch.setattr(uia_app.uia, "send_keys", sent.append)

    class Window:
        def set_focus(self) -> None:
            sent.append("focus")

    uia_app.App(None, Window()).send("{ESC}")
    assert sent == ["{ESC}"]
