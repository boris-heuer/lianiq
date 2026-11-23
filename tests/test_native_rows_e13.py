"""Unit tests of the UIA row E-13 with a faked window and cable (CAP-0172 AC-37).

The real window, pywinauto and VB-Cable exist only in the VM image; ``FakeTextApp`` stands
in for the Text translation page as UI Automation reads it. The tests pin the pass rule
(cable Speakers, fixture typed, result as SHA-256 only, "Text translation running", F9 back
to idle with **Replay**, texts unchanged, both panes masked) and that each step can fail.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from native_e2e.evidence.model import Method, Status
from native_e2e.rows import e13
from native_e2e.uia import Node
from tests._native_fake_app import make_ctx
from tests._native_png import red_png

CABLE_IN = "CABLE Input (VB-Audio Virtual Cable)"
RESULT = "早上好。今天我们测试文本翻译。\n\n第二段有两句话。到此结束。"
SOURCE_RECT, RESULT_RECT = (120, 200, 480, 600), (500, 200, 880, 600)
ENTRIES = ("Conversation", "Meeting", "Text translation", "Settings")


class FakeTextApp:
    rect = (100, 100, 900, 700)

    def __init__(self, translate=True, play=True, f9=True, speakers=True) -> None:
        self.knobs = {"translate": translate, "play": play, "f9": f9, "speakers": speakers}
        self.page, self.speakers = "Conversation", "Follow Windows default"
        self.source = self.result = ""
        self.playing = self.replay = self.closed = False

    def nodes(self) -> list[Node]:
        nodes = [
            Node(name, "CheckBox", selected=name == self.page, parents=("Workspaces",))
            for name in ENTRIES
        ]
        if self.page == "Settings" and self.knobs["speakers"]:
            nodes.append(Node("Speakers", "ComboBox", value=self.speakers))
        if self.page == "Text translation":
            play = "Stop" if self.playing else "Replay" if self.replay else "Play translation"
            nodes += [
                Node("Source text", "Text"),
                Node(
                    "Source text", "Edit", value=self.source.replace("\n", "\r"), rect=SOURCE_RECT
                ),
                Node("Translation", "Text"),
                Node("Translation", "Edit", value=self.result, rect=RESULT_RECT),
                Node("Translate", "Button", enabled=bool(self.source)),
                Node(play, "Button", enabled=bool(self.result)),
            ]
        if self.playing:
            nodes += [Node("Active session", "Group"), Node("Text translation running", "Text")]
        return nodes

    def press(self, node: Node) -> None:
        if node.name in ENTRIES:
            self.page = node.name
        elif node.name == "Translate" and self.knobs["translate"]:
            self.result = RESULT
        elif node.name == "Play translation" and self.knobs["play"]:
            self.playing = True

    def keys(self, text: str) -> None:
        if text == "{F9}":
            if self.knobs["f9"]:
                self.playing, self.replay = False, True
            return
        self.source = text.replace("^a{DELETE}", "").replace("{ENTER}", "\n")

    def choose(self, node: Node, item: str) -> None:
        self.speakers = item

    def close(self) -> int:
        self.closed = True
        return 0


@pytest.fixture
def ctx(tmp_path):
    return make_ctx(tmp_path)


def run_e13(ctx, monkeypatch, **knobs):
    from native_e2e import audio, screens, uia_app
    from native_e2e.rows import ui

    app = FakeTextApp(**knobs)
    monkeypatch.setattr(uia_app, "launch", lambda _ctx: app)
    monkeypatch.setattr(screens, "grab", red_png)
    monkeypatch.setattr(audio, "wasapi_name", lambda prefix, kind: CABLE_IN)
    monkeypatch.setattr(audio, "endpoint_names", lambda: [CABLE_IN])
    monkeypatch.setattr(ui, "TIMEOUT_S", 0.3)
    monkeypatch.setattr(ui, "MODEL_TIMEOUT_S", 0.3)
    monkeypatch.setattr(ui, "POLL_S", 0.01)
    masked: list[list] = []
    write = screens.write_masked
    monkeypatch.setattr(
        screens,
        "write_masked",
        lambda c, rel, png, origin, rects: (
            masked.append(list(rects)) or write(c, rel, png, origin, rects)
        ),
    )
    return e13.run(ctx), app, masked


def test_e13_passes_and_stores_the_result_as_sha256_only(ctx, monkeypatch) -> None:
    row, app, masked = run_e13(ctx, monkeypatch)
    assert row.status is Status.PASS, row.checks
    assert row.method is Method.VIRTUAL_DEVICE and row.acs == ("AC-37",)
    assert [check.name for check in row.checks] == [
        "speakers-cable-selected",
        "fixture-typed",
        "translation-shown",
        "screenshot-result-masked",
        "strip-text-translation-running",
        "screenshot-playing-masked",
        "stopped-with-f9-idle",
        "texts-unchanged",
    ]
    assert app.speakers == CABLE_IN and app.source == e13.FIXTURE and app.closed
    digest = hashlib.sha256(RESULT.encode("utf-8")).hexdigest()
    assert row.checks[2].detail == f"sha256={digest}"
    assert [artifact.path for artifact in row.artifacts] == list(e13.SCREENS)
    assert all((ctx.out / path).is_file() for path in e13.SCREENS)
    assert len(masked) == 2 and all({SOURCE_RECT, RESULT_RECT} <= set(rects) for rects in masked)
    stored = json.dumps(row.to_dict(), ensure_ascii=False)
    assert "Guten" not in stored and "早上好" not in stored and "CABLE" not in stored
    assert {*e13.PARAGRAPHS, "第二段有两句话。到此结束。"} <= set(ctx.secrets)


@pytest.mark.parametrize(
    ("knobs", "failed"),
    [
        ({"speakers": False}, "speakers-cable-selected"),
        ({"translate": False}, "translation-shown"),
        ({"play": False}, "strip-text-translation-running"),
        ({"f9": False}, "stopped-with-f9-idle"),
    ],
)
def test_e13_fails_on_each_missing_step_and_still_closes(ctx, monkeypatch, knobs, failed) -> None:
    row, app, _masked = run_e13(ctx, monkeypatch, **knobs)
    assert row.status is Status.FAIL and row.reason == "text-translation"
    assert [check.name for check in row.checks if check.result is Status.FAIL] == [failed]
    assert app.closed
