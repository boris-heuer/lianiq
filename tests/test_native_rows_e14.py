"""Unit tests of the UIA row E-14 with a faked Listen page and cable (CAP-0170 AC-31).

E-14 passes only when the pinned fixture is unchanged (checked before any app starts), the
Listen page shows two done *Transcript* rows for German → Mandarin (Simplified) from the
cable, F9 returns it to idle and the app process has no render session. The evidence holds
the translations' SHA-256 only; every row text is a redaction secret.
"""

from __future__ import annotations

import json

import pytest

from native_e2e import audio_sessions
from native_e2e.evidence.model import Method, Status
from native_e2e.rows import e14
from native_e2e.uia import Node
from tests import _native_real_tree as real
from tests._native_fake_app import CABLE, DEFAULT_MIC, SIDEBAR, install, make_ctx

TOP = ("lianiq",)
SOURCES = ("Guten Morgen, wie geht es Ihnen?", "Heute ist das Wetter sehr schön.")
TRANSLATIONS = ("早上好，你好吗？", "今天天气很好。")
PID = 4242


def row_text(second: int, source: str, outcome: str) -> str:
    return f"10:00:0{second}, German: {source}. Mandarin (Simplified): {outcome}"


class ListenApp:
    """The Listen page as UI Automation reads it; knobs make one pass rule fail."""

    rect = (100, 100, 900, 700)

    def __init__(self, **knobs) -> None:
        self.knobs, self.page, self.running, self.closed = knobs, "Conversation", False, False
        self.values = {"Source language": "English", "Target language": "German"}
        self.values["Microphone"] = DEFAULT_MIC
        self.rows: list[str] = []
        self.launches = 0
        self.readonly: set = set()

    def start(self, ctx):
        self.launches += 1
        return self

    def nodes(self) -> list[Node]:
        out = [
            Node(label, real.NAV_ENTRY, enabled=on, selected=label == self.page, description=d,
                 rect=(100, 110 + 40 * i, 300, 140 + 40 * i), parents=(*TOP, "Workspaces"))
            for i, (label, on, d) in enumerate(SIDEBAR)
        ]  # fmt: skip
        if self.running:
            name = "Listen & translate running"
            out.append(Node("Active session", "Group", description=name, parents=TOP))
        if self.page != "Listen & translate":
            return out
        out += [
            Node(label, "ComboBox", value=value, rect=(320, 200, 700, 230), parents=TOP)
            for label, value in self.values.items()
        ]
        out += [
            Node("Start listening (F8)", "Button", enabled=not self.running, parents=TOP),
            Node("Listening…" if self.running else "Ready", "Text", parents=TOP),
            Node("Transcript", "List", rect=(320, 300, 880, 600), parents=TOP),
            *(Node(text, "ListItem", parents=(*TOP, "Transcript")) for text in self.rows),
        ]
        return out

    def press(self, node: Node) -> None:
        if "Workspaces" in node.parents:
            self.page = node.name
        elif node.name == "Start listening (F8)" and node.enabled:
            self.running = True

    def choose(self, node: Node, item: str) -> None:
        if node.name == "Microphone" and item != CABLE:
            raise IndexError("item not found")
        self.values[node.name] = item

    def keys(self, text: str) -> None:
        if text == "{F9}":
            self.running = False

    def hear_phrase(self) -> None:
        last = "Translating…" if self.knobs.get("pending") else TRANSLATIONS[1]
        outcomes = (TRANSLATIONS[0], last)
        self.rows = [row_text(i, s, o) for i, (s, o) in enumerate(zip(SOURCES, outcomes))]

    def pids(self) -> list[int]:
        return [PID]

    def close(self) -> int:
        self.closed = True
        return 0


@pytest.fixture
def ctx(tmp_path):
    return make_ctx(tmp_path)


def run_e14(ctx, monkeypatch, render=frozenset(), **knobs):
    app = ListenApp(**knobs)
    install(monkeypatch, app)
    monkeypatch.setattr(audio_sessions, "render_pids", lambda: set(render))
    return e14.run(ctx), app


def failed(row) -> list[str]:
    return [check.name for check in row.checks if check.result is not Status.PASS]


def test_e14_checks_the_fixture_before_any_app_starts(ctx, monkeypatch) -> None:
    monkeypatch.setattr(e14, "FIXTURE_SHA256", "0" * 64)
    row, app = run_e14(ctx, monkeypatch)
    assert row.status is Status.FAIL and failed(row) == ["listen-fixture-sha256"]
    assert app.launches == 0 and row.reason == "listen-fixture"


def test_e14_passes_and_stores_only_the_translations_sha256(ctx, monkeypatch) -> None:
    row, app = run_e14(ctx, monkeypatch, render={1, 2})  # other processes' sessions
    assert row.status is Status.PASS, row.checks
    assert row.method is Method.VIRTUAL_DEVICE and row.acs == ("AC-31",)
    assert [check.name for check in row.checks] == [
        "listen-fixture-sha256",
        "pair-german-to-mandarin",
        "microphone-cable-selected",
        "start-listening",
        "session-running",
        "two-done-rows",
        "translations-sha256",
        "strip-shows-running",
        "stopped-with-f9",
        "no-render-stream",
        "screenshot-masked",
    ]
    details = {check.name: check.detail for check in row.checks}
    assert details["translations-sha256"] == f"sha256={e14.digest(list(TRANSLATIONS))}"
    assert details["microphone-cable-selected"] == "name_matches: true"
    text = json.dumps(row.to_dict(), ensure_ascii=False)
    for secret in (*SOURCES, *TRANSLATIONS, CABLE):
        assert secret not in text
        assert secret in ctx.secrets or secret == CABLE  # the scan fails on any copy
    assert [a.path for a in row.artifacts] == [e14.SCREEN] and ctx.state["screens_masked"] == 1
    assert app.closed and app.launches == 1 and "app" not in ctx.state


def test_e14_fails_when_the_app_opened_a_render_stream(ctx, monkeypatch) -> None:
    row, app = run_e14(ctx, monkeypatch, render={PID})
    assert failed(row) == ["no-render-stream"] and app.closed
    assert {c.name: c.detail for c in row.checks}["no-render-stream"] == "render_sessions=1"


def test_e14_fails_while_a_row_is_still_pending(ctx, monkeypatch) -> None:
    row, app = run_e14(ctx, monkeypatch, pending=True)
    assert failed(row) == ["two-done-rows"] and app.closed
    assert "今天天气很好" not in json.dumps(row.to_dict(), ensure_ascii=False)
