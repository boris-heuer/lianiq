"""Unit tests of the Call Bridge rows E-34..E-38 with a faked window and cables (CAP-0166).

The fake models the Call Bridge page as UI Automation reads it (path boxes, role combos, lane
status and route-test lines, readiness list, Start/Stop, live text) and the cables as speech
intervals on the ``perf_counter`` clock: the headset ("CABLE Output") and the call microphone cable
("CABLE-A Output"). Knobs break one behaviour each, so the pass rules can be shown to fail.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy
import pytest

from lianiq.ui import strings_call_bridge as t
from native_e2e import audio, audio_sessions
from native_e2e.evidence.model import Method, Status
from native_e2e.rows import cb, e34, e36, e37
from native_e2e.uia import Node
from tests._native_fake_app import FakeApp, install, make_ctx

ROOT = Path(__file__).resolve().parents[1]
NAMES = {
    "mic": "CABLE Output (VB-Audio Virtual Cable)",
    "headphones": "CABLE Input (VB-Audio Virtual Cable)",
    "a_in": "CABLE-A Input (VB-Audio Cable A)",
    "a_out": "CABLE-A Output (VB-Audio Cable A)",
    "b_in": "CABLE-B Input (VB-Audio Cable B)",
    "b_out": "CABLE-B Output (VB-Audio Cable B)",
}
OUT, IN = t.CB_PATH_OUT_NAME, t.CB_PATH_IN_NAME
TITLES = {OUT: f"{OUT} · German → Mandarin (Simplified)", IN: f"{IN} · Mandarin → German"}
ROLES = {
    t.CB_ROLE_LOCAL_MIC: OUT,
    t.CB_ROLE_CALL_MIC: OUT,
    t.CB_ROLE_CALL_SPEAKER: IN,
    t.CB_ROLE_HEADPHONES: IN,
}
ROWS = (e34.e34, e34.e35, e36.e36, e37.e37, e37.e38)


class CallApp(FakeApp):
    def __init__(self, **knobs) -> None:
        super().__init__(**knobs)
        self.combo = dict.fromkeys(ROLES, t.CB_SELECT)
        self.lane = dict.fromkeys(TITLES, t.CB_LANE_STOPPED)
        self.test = dict.fromkeys(TITLES, t.CB_T_NOT_TESTED)
        self.bridge, self.items, self.had_block = False, [], None
        self.cables: dict[str, list] = {"a": [], "h": []}

    def start(self, ctx):
        settings = json.loads(ctx.local_settings.read_text(encoding="utf-8"))
        self.had_block = "call_bridge" in settings
        return super().start(ctx)

    def pids(self) -> list[int]:
        return [4242]

    def sound(self, cable: str) -> None:
        now = time.perf_counter()
        self.cables[cable].append((now, now + 0.02))

    def reasons(self) -> list[str]:
        found = [t.CB_R_SELECT.format(role=r) for r, v in self.combo.items() if v == t.CB_SELECT]
        same = self.combo[t.CB_ROLE_CALL_SPEAKER] == NAMES["a_out"]
        return found + ([t.CB_R_SAME_CABLE] if same and not self.knobs.get("no_same") else [])

    def _call(self, top) -> list[Node]:
        nodes = [Node(t.CB_EXPERIMENTAL, "Text"), Node(t.CB_CHECKLIST_LINK, "Hyperlink")]
        for path, title in TITLES.items():
            box = (*top, title)
            asking = self.test[path] in (t.CB_Q_OUT, t.CB_Q_IN)
            nodes += [
                Node(title, "Group", parents=top),
                *(
                    Node(role, "ComboBox", enabled=not self.bridge, value=value, parents=box)
                    for role, value in self.combo.items()
                    if ROLES[role] == path
                ),
                Node(f"{t.CB_LANE_STATUS}: {self.lane[path]}", "Text", parents=box),
                Node(f"{t.CB_TEST_ROW}: {self.test[path]}", "Text", parents=box),
                Node(f"{t.CB_YES if asking else t.CB_TEST} · {path}", "Button", parents=box),
            ]
        nodes += [Node(t.CB_LEVEL_MIC, "ProgressBar"), Node(t.CB_LEVEL_CALL, "ProgressBar")]
        nodes += [Node(r, "Text", parents=(*top, t.CB_READINESS)) for r in self.reasons()]
        nodes += [Node(item, "ListItem", parents=(*top, t.CB_TEXT_TITLE)) for item in self.items]
        ready = not self.reasons() and not self.bridge
        return [
            *nodes,
            Node(cb.START, "Button", enabled=ready),
            Node(cb.STOP, "Button", enabled=self.bridge),
        ]

    def choose(self, node, item: str) -> None:
        if node.name not in ROLES:
            return super().choose(node, item)
        path = ROLES[node.name]
        changed = self.combo[node.name] != item and not self.knobs.get("no_reset")
        if changed and self.test[path] == t.CB_T_PASSED:
            self.test[path] = t.CB_T_NOT_TESTED
        self.combo[node.name] = item

    def press(self, node: Node) -> None:
        path = node.name.split(" · ", 1)[-1]
        if node.name == cb.START:
            self.bridge, self.items = True, []
            self.lane = dict.fromkeys(TITLES, t.CB_LANE_LISTENING)
        elif node.name.startswith(f"{t.CB_TEST} · "):
            inbound = (path == IN) != bool(self.knobs.get("wrong_cable"))
            self.sound("h" if inbound else "a")
            self.test[path] = t.CB_Q_IN if path == IN else t.CB_Q_OUT
        elif node.name.startswith(f"{t.CB_YES} · "):
            self.test[path] = t.CB_T_PASSED
        else:
            super().press(node)

    def keys(self, text: str) -> None:
        super().keys(text)
        if text == "{F9}" and not self.knobs.get("f9_ignored"):
            self.bridge = False
            self.lane = dict.fromkeys(TITLES, t.CB_LANE_STOPPED)

    def hear(self, prefix: str, rate, frames) -> float:
        end = time.perf_counter()
        if self.bridge and prefix == audio.CABLE_INPUT:  # G1 into *Your microphone*
            self.items.append(f"{OUT} · Guten Morgen, das ist ein Test. · 早上好，这是一个测试。")
            self.lane[OUT] = t.CB_LANE_SPEAKING
            self.sound("a")
        elif self.bridge and prefix == cb.B_IN:  # the call partner into the speaker cable
            self.items.append(f"{IN} · 早上好，测试一下。 · Guten Morgen, ein Test.")
            self.lane[IN], self.lane[OUT] = t.CB_LANE_SPEAKING, t.CB_LANE_ECHO_PAUSED
            self.sound("h")
            if self.knobs.get("echo_leak"):
                self.sound("a")
        return end


class FakeRecorder:
    def __init__(self, app: CallApp, prefix: str) -> None:
        self.spans = app.cables["a" if prefix == cb.A_OUT else "h"]

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        return None

    def span(self, since: float, until: float | None = None):
        hits = [s for s in self.spans if s[1] > since and (until is None or s[0] < until)]
        return (hits[0][0], hits[-1][1]) if hits else None

    def between(self, since: float, until: float | None = None):
        return 16000, numpy.zeros(1600, dtype="float32")


def run_rows(tmp_path, monkeypatch, names=NAMES, upto=5, **knobs):
    ctx = make_ctx(tmp_path)
    ctx.local_settings.write_text(json.dumps({"audio": {}, "call_bridge": {}}), "utf-8")
    ctx.state["settings_backup"] = {"existed": False}
    app = CallApp(**knobs)
    install(monkeypatch, app)
    monkeypatch.setattr(cb, "endpoints", lambda: dict(names) if names else None)
    monkeypatch.setattr(cb, "Recorder", lambda prefix: FakeRecorder(app, prefix))
    monkeypatch.setattr(cb, "inject", app.hear)
    monkeypatch.setattr(cb, "beep", lambda: None)
    monkeypatch.setattr(cb, "synth_wav", lambda ctx: None)
    monkeypatch.setattr(audio_sessions, "render_pids", set)
    for name, value in (("SETTLE_S", 0.01), ("QUIET_S", 0.05), ("NOTIFY_S", 0.05)):
        monkeypatch.setattr(cb, name, value)
    return ctx, app, [row(ctx) for row in ROWS[:upto]]


def failed(rows) -> set[str]:
    return {check.name for row in rows for check in row.checks if check.result is Status.FAIL}


def test_e34_to_e38_pass_with_three_cables(tmp_path, monkeypatch) -> None:
    ctx, app, rows = run_rows(tmp_path, monkeypatch)
    assert [row.status for row in rows] == [Status.PASS] * 5, [r.checks for r in rows]
    assert [row.id for row in rows] == ["E-34", "E-35", "E-36", "E-37", "E-38"]
    assert rows[0].acs == ("AC-01", "AC-02") and rows[3].method is Method.VIRTUAL_DEVICE
    assert app.launches == 1 and app.closed and app.had_block is False
    assert "app" not in ctx.state and "cb_zh" not in ctx.state
    assert not ctx.local_settings.exists()  # settings_reset: no file before S-03
    shots = [a.path for row in rows for a in row.artifacts]
    assert "screens/e37-running.png" in shots and len(shots) == 7
    text = json.dumps([row.to_dict() for row in rows], ensure_ascii=False)
    for leak in ("CABLE-A", "CABLE-B", "Guten Morgen", "早上好"):
        assert leak not in text
    assert set(NAMES.values()) <= set(ctx.secrets) and "早上好，这是一个测试。" in ctx.secrets
    detail = next(c.detail for c in rows[3].checks if c.name == "german-in-headset")
    assert detail.startswith("latency_s=") and detail.endswith("source=loopback")


def test_e38_closes_the_app_and_resets_the_settings_when_it_raises(tmp_path, monkeypatch) -> None:
    ctx, app, rows = run_rows(tmp_path, monkeypatch, upto=4)
    assert rows[-1].status is Status.PASS and not app.closed

    def broken(*_args):
        raise RuntimeError("cable gone")

    monkeypatch.setattr(cb, "inject", broken)
    with pytest.raises(RuntimeError):
        e37.e38(ctx)
    assert app.closed and "app" not in ctx.state and not ctx.local_settings.exists()


def test_without_cable_ab_every_row_is_blocked_and_no_app_starts(tmp_path, monkeypatch) -> None:
    _ctx, app, rows = run_rows(tmp_path, monkeypatch, names=None)
    assert {row.status for row in rows} == {Status.BLOCKED} and app.launches == 0
    assert {row.reason for row in rows} == {cb.BLOCKED}


@pytest.mark.parametrize(
    ("knobs", "check"),
    [
        ({"no_same": True}, "same-cable-listed"),
        ({"wrong_cable": True}, "in-test-in-headset"),
        ({"no_reset": True}, "change-resets-call-to-you-only"),
        ({"echo_leak": True}, "call-cable-silent-during-inbound"),
        ({"echo_leak": True}, "nothing-sent-while-paused"),
        ({"f9_ignored": True}, "f9-stops-both-lanes"),
    ],
)
def test_a_broken_behaviour_fails_its_row(tmp_path, monkeypatch, knobs, check) -> None:
    _ctx, app, rows = run_rows(tmp_path, monkeypatch, **knobs)
    assert check in failed(rows) and app.closed


def test_start_and_stop_labels_are_the_panels() -> None:
    panel = (ROOT / "lianiq" / "ui" / "call_bridge_panel.py").read_text(encoding="utf-8")
    assert f'QPushButton("{cb.START}")' in panel and f'QPushButton("{cb.STOP}")' in panel
