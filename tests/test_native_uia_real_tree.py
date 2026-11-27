"""The UIA helpers against the tree the real Qt window shows (local probes after native run 44267851808).

Read from ``python -m lianiq`` with pywinauto ``backend="uia"``: the sidebar entries are
``CheckBox`` elements, the notice history is an ``Edit`` inside a group box of the same name,
the transcript panels have no Scroll pattern and show a scroll bar only once the text
overflows, and a combo box lists its items only while expanded, where only a real click
commits one.
"""

from __future__ import annotations

import ast
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from native_e2e import uia, uia_app
from native_e2e.rows import e03, e10, ui
from native_e2e.uia import Node
from tests import _native_real_tree as real

ROOT = Path(__file__).resolve().parents[1]
TOP = ("lianiq",)


def test_sidebar_lists_the_checkbox_entries_of_the_region() -> None:
    nodes = [
        Node("Workspaces", "Custom", parents=TOP),
        Node("Conversation", "CheckBox", selected=True, parents=(*TOP, "Workspaces")),
        Node("Settings", "CheckBox", parents=(*TOP, "Workspaces")),
        Node("Speak German", "CheckBox", parents=TOP),  # outside the region
    ]
    assert [node.name for node in ui.sidebar(nodes, "Workspaces")] == ["Conversation", "Settings"]


def test_history_reads_the_edit_field_not_its_group_box() -> None:
    s = SimpleNamespace(DIAG_HISTORY="Notice history")
    nodes = [
        Node("Notice history", "Group", value="", parents=TOP),
        Node("Notice history", "Edit", value="a\n\nb\n", parents=(*TOP, "Notice history")),
    ]
    assert e10._history(nodes, s) == ["a", "b"]


@pytest.mark.parametrize(
    ("bars", "expected"),
    [
        ([], 0.0),  # the text fits: nothing is scrolled
        ([Node("", "ScrollBar", scroll=0.4567, parents=(*TOP, "Transcript"))], 0.457),
        ([Node("", "ScrollBar", scroll=None, parents=(*TOP, "Transcript"))], None),
        ([Node("", "ScrollBar", scroll=0.5, visible=False, parents=(*TOP, "Transcript"))], 0.0),
        ([Node("", "ScrollBar", scroll=0.5, parents=(*TOP, "Settings"))], 0.0),
    ],
)
def test_panel_scroll_without_a_scroll_pattern(bars, expected) -> None:
    field = Node("Transcript", "List", parents=TOP)
    assert e03._scroll([field, *bars], field) == expected


def test_panel_scroll_of_a_missing_field_is_unreadable() -> None:
    assert e03._scroll([], None) is None


class _Item:
    def __init__(self, name: str, clicks: list[str]) -> None:
        self.element_info = SimpleNamespace(name=name)
        self._clicks = clicks

    def click_input(self) -> None:
        self._clicks.append(self.element_info.name)


class _Combo:
    """A collapsed Qt combo box: it lists its items only once expanded."""

    def __init__(self, items: list[str]) -> None:
        self.items = items
        self.expanded = False
        self.clicks: list[str] = []

    def expand(self) -> None:
        self.expanded = True

    def collapse(self) -> None:
        self.expanded = False

    def descendants(self, control_type: str | None = None) -> list[_Item]:
        assert control_type == "ListItem"
        return [_Item(name, self.clicks) for name in self.items] if self.expanded else []

    def select(self, item: str) -> None:  # pywinauto's own select finds no Qt item
        raise IndexError(item)


def _app(combo: _Combo) -> tuple[uia_app.App, Node]:
    window = SimpleNamespace(set_focus=lambda: None)
    return uia_app.App(process=None, window=window), Node("Microphone", "ComboBox", handle=combo)


def test_choose_expands_the_combo_box_and_clicks_the_item() -> None:
    combo = _Combo(["Follow Windows default", "CABLE Output (VB-Audio Virtual Cable)"])
    app, node = _app(combo)
    app.choose(node, "CABLE Output (VB-Audio Virtual Cable)")
    assert combo.clicks == ["CABLE Output (VB-Audio Virtual Cable)"]


def test_choose_times_out_and_collapses_when_the_item_is_not_listed(monkeypatch) -> None:
    monkeypatch.setattr(uia, "UIA_TIMEOUT_S", 0.05)
    combo = _Combo(["Follow Windows default"])
    app, node = _app(combo)
    with pytest.raises(TimeoutError):
        app.choose(node, "CABLE Output (VB-Audio Virtual Cable)")
    assert combo.clicks == []
    assert combo.expanded is False


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    return next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _single_shots(function: ast.FunctionDef) -> list[str]:
    return [
        ast.unparse(call)
        for call in ast.walk(function)
        if isinstance(call, ast.Call) and ast.unparse(call.func) == "QTimer.singleShot"
    ]


def test_ui_self_test_times_the_turn_from_model_readiness() -> None:
    """C-03: the model load has its own budget; the 90 s run from ``session_ready``."""
    tree = ast.parse((ROOT / "scripts" / "ui_self_test.py").read_text(encoding="utf-8"))
    values = {
        target.id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert values["TURN_TIMEOUT_MS"] == 90_000
    assert values["WARM_UP_TIMEOUT_MS"] + values["TURN_TIMEOUT_MS"] < 900_000  # C-03 budget
    main = _function(tree, "main")
    assert "QTimer.singleShot(TURN_TIMEOUT_MS, on_timeout)" in _single_shots(
        _function(main, "on_session_ready")
    )
    assert "QTimer.singleShot(WARM_UP_TIMEOUT_MS, on_warm_up_timeout)" in _single_shots(main)
    assert not any("on_timeout)" in call and "TURN" not in call for call in _single_shots(main))


class _Element:
    def __init__(self, name: str, children=()) -> None:
        self._children = list(children)
        self.element_info = SimpleNamespace(
            name=name,
            control_type="Button",
            enabled=True,
            visible=True,
            automation_id="",
            element=None,
            rectangle=SimpleNamespace(left=0, top=0, right=10, bottom=10),
        )

    def children(self):
        return self._children


def test_snapshot_skips_an_element_that_vanishes_while_read(monkeypatch) -> None:
    real = uia.read_node

    def read(element, parents=()):
        if element.element_info.name == "closing":
            raise OSError("element not available")
        return real(element, parents)

    monkeypatch.setattr(uia, "read_node", read)
    root = _Element("lianiq", [_Element("closing", [_Element("inner")]), _Element("Export…")])
    assert [node.name for node in uia.snapshot(root)] == ["Export…"]


class _Clickable:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    def click_input(self) -> None:
        self.log.append("click")

    def set_focus(self) -> None:
        self.log.append("focus")


def test_press_uses_the_keyboard_for_an_element_below_the_fold(monkeypatch) -> None:
    """Export… lay at y 1087-1134 under a window ending at 1038 (Settings scrolls)."""
    log: list[str] = []
    monkeypatch.setattr(uia, "send_keys", lambda keys: log.append(keys))
    window = SimpleNamespace(
        set_focus=lambda: None,
        rectangle=lambda: SimpleNamespace(left=160, top=138, right=1760, bottom=1038),
    )
    app = uia_app.App(process=None, window=window)
    app.press(Node("Export…", "Button", rect=(532, 1087, 632, 1134), handle=_Clickable(log)))
    assert log == ["focus", "{SPACE}"]
    log.clear()
    app.press(Node("Settings", "CheckBox", rect=(170, 700, 360, 740), handle=_Clickable(log)))
    assert log == ["click"]


def test_deny_write_writes_the_file_and_proves_the_refused_append(tmp_path, monkeypatch) -> None:
    """E-10 protects a file in a writable folder (PO decision after native run 44267851808)."""
    calls: list[list[str]] = []

    def icacls(args, **kwargs):
        calls.append(args)
        os.chmod(args[1], stat.S_IREAD)

    monkeypatch.setenv("USERNAME", "e2e")
    monkeypatch.setattr(e10.subprocess, "run", icacls)
    path = tmp_path / "ro" / "diagnostics-E10.txt"
    try:
        assert e10.deny_write(path) is True
    finally:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    assert calls == [["icacls", str(path), "/deny", "e2e:(WD,AD,WEA,WA)"]]
    assert path.read_text(encoding="utf-8") == e10.PROTECTED_CONTENT
    assert e10._unchanged(path)


def test_deny_write_fails_when_the_file_stays_writable(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("USERNAME", "e2e")
    monkeypatch.setattr(e10.subprocess, "run", lambda args, **kwargs: None)
    path = tmp_path / "ro" / "diagnostics-E10.txt"
    assert e10.deny_write(path) is False
    assert not e10._unchanged(path)  # the probe appended


def test_replace_yes_is_the_task_dialog_yes_button() -> None:
    """In the real save dialog "Ja" is CommandButton_6 inside "Speichern unter bestätigen"."""
    assert e10._replace_yes(list(real.SAVE_DIALOG)) is None
    yes = e10._replace_yes([*real.SAVE_DIALOG, *real.REPLACE_PROMPT])
    assert (yes.control_type, yes.automation_id) == ("Button", "CommandButton_6")


def test_model_readiness_waits_300_seconds() -> None:
    """E-03 contract after native run 44267851808: the cold VM needs more than 120 s."""
    assert uia.MODEL_TIMEOUT_S == ui.MODEL_TIMEOUT_S == 300.0
