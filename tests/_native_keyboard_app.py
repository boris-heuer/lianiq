"""A keyboard-driven stand-in for the Lianiq window, as UI Automation reads it (E-31..E-33).

It models the Tab cycle of the main window (sidebar, then the shown page) and of each open
dialog, the focused element, Space, Enter, Escape, F8/F9, Ctrl+1…7, Ctrl+Enter and the few
editing keys the rows type. Knobs break one behaviour each, so every pass rule can be shown
to fail; ``removed`` and ``downloaded`` record a key that confirmed a dialog (never wanted).
"""

from __future__ import annotations

import re

from lianiq.ui import strings as s
from native_e2e.uia import Node
from tests._native_fake_app import CABLE, SIDEBAR, WINDOW

TRANSLATION = "早上好。今天我们测试文本翻译。"
MODELS = ("Model A", "Model B")
OPTIONS = "Voice options for Mandarin (Simplified)"
_TOKEN = re.compile(r"\^\{ENTER\}|\^.|\{[A-Z0-9]+\}|\{.\}|.", re.DOTALL)


def _node(name: str, kind: str, index: int, **extra) -> Node:
    return Node(name, kind, rect=(300, 100 + 10 * index, 400, 108 + 10 * index), **extra)


DIALOGS = {
    "Voice options — Mandarin (Simplified)": (("Rate", "Slider"), ("Close", "Button")),
    s.DIAG_EXPORT_TITLE: (("File name:", "Edit"), ("Save", "Button"), ("Cancel", "Button")),
    s.ASSIST_TITLE: ((s.ASSIST_USAGE_TITLE, "List"), (s.ASSIST_SKIP, "Button")),
    "Model B": (("I accept the licence (MIT)", "CheckBox"), (s.PACK_IMPORT, "Button")),
    s.PACK_REMOVE: (("Yes", "Button"), ("Cancel", "Button")),
}
OPENS = {
    OPTIONS: "Voice options — Mandarin (Simplified)",
    s.DIAG_EXPORT: s.DIAG_EXPORT_TITLE,
    s.PACKS_RUN_ASSISTANT: s.ASSIST_TITLE,
    s.PACK_GET: "Model B",
    s.PACK_REMOVE: s.PACK_REMOVE,
}


class KeyApp:
    rect = WINDOW

    def __init__(self, **knobs) -> None:
        self.knobs, self.page, self.dialog, self.focus = knobs, "Conversation", None, -1
        self.voices = {"Speak German": True, "Speak Mandarin (Simplified)": False}
        self.combos = {s.LISTEN_SOURCE_LANGUAGE: "German", s.LISTEN_TARGET_LANGUAGE: "German"}
        self.combos[s.LISTEN_MICROPHONE] = "Follow Windows default"
        self.source = self.result = self.status = self.clipboard = ""
        self.translating = self.listening = self.selected_all = False
        self.removed = self.downloaded = False
        self.closed, self.launches, self.ctx, self.back = False, 0, None, -1

    def start(self, ctx):
        self.ctx, self.closed = ctx, False
        self.launches += 1
        return self

    def close(self) -> int:
        self.closed = True
        return 0

    # What UI Automation reads

    def _page(self) -> list[Node]:
        k, page = self.knobs, self.page
        if page == "Conversation":
            out = [
                _node(n, "CheckBox", 20 + i, selected=on)
                for i, (n, on) in enumerate(self.voices.items())
            ]
            out += [_node(OPTIONS, "Button", 23), _node("▶  Start  (F8)", "Button", 24)]
        elif page == "Settings":
            out = [_node("Microphone", "ComboBox", 20), _node(s.DIAG_EXPORT, "Button", 21)]
        elif page == "Listen & translate":
            out = [
                _node(n, "ComboBox", 20 + i, value=v)
                for i, (n, v) in enumerate(self.combos.items())
            ]
            state = s.LISTEN_STATE_LISTENING if self.listening else s.LISTEN_STATE_READY
            start = _node(s.LISTEN_START, "Button", 24, enabled=not self.listening)
            out += [start, _node(state, "Text", 25)]
        elif page == "Text translation":
            label = s.TEXT_CANCEL if self.translating else s.TEXT_TRANSLATE
            out = [
                _node(s.TEXT_SOURCE_LABEL, "Edit", 20, value=self.source),
                _node(s.TEXT_RESULT_LABEL, "Edit", 21, value=self.result),
                _node(label, "Button", 22, enabled=bool(self.source)),
                _node(self.status, "Text", 23),
            ]
        elif page == "Language packs":
            rows = [f"{MODELS[0]}, {s.PACK_STATE_VALIDATED}", f"{MODELS[1]}, Downloadable"]
            if self.knobs.get("checking"):
                rows[1] = f"{MODELS[1]}, {s.PACK_STATE_CHECKING}"
            out = [_node(s.PACKS_RUN_ASSISTANT, "Button", 20)]
            out += [_node(rows[0], "Group", 21), _node(rows[1], "Group", 22)]
            if not k.get("no_remove"):
                out.append(_node(s.PACK_REMOVE, "Button", 23, parents=("lianiq", rows[0])))
            if not k.get("no_get"):
                out.append(_node(s.PACK_GET, "Button", 24, parents=("lianiq", rows[1])))
        else:
            out = []
        if k.get("unnamed") == page:
            out.append(_node("", "Button", 30))
        return out

    def nodes(self) -> list[Node]:
        sidebar = [
            _node(
                label, "CheckBox", i, selected=label == self.page, parents=("lianiq", "Workspaces")
            )
            for i, (label, _enabled, _desc) in enumerate(SIDEBAR)
        ]
        strip = []
        if self.listening:
            strip = [_node(s.SESSION_RUNNING.format(mode=s.NAV_LISTEN), "Text", 40)]
        return [*sidebar, *self._page(), *strip]

    def _stops(self) -> list[Node]:
        if self.dialog is not None:
            pairs = DIALOGS[self.dialog]
            return [_node(name, kind, 50 + i) for i, (name, kind) in enumerate(pairs)]
        return [n for n in self.nodes() if n.control_type not in ("Text", "Group") and n.enabled]

    def focused(self) -> Node | None:
        stops = self._stops()
        return stops[self.focus] if 0 <= self.focus < len(stops) else None

    def window_nodes(self, title: str) -> list[Node] | None:
        return self._stops() if self.dialog == title else None

    # Actions

    def _show(self, page: str) -> None:
        self.page, self.focus = page, -1

    def press(self, node: Node) -> None:
        if "Workspaces" in node.parents:
            return self._show(node.name)
        names = [n.name for n in self._stops()]
        self.focus = names.index(node.name) if node.name in names else self.focus

    def choose(self, node: Node, item: str) -> None:
        if node.name == s.LISTEN_MICROPHONE and item != CABLE:
            raise IndexError("item not found")
        self.combos[node.name] = item

    def _translate(self) -> None:
        if self.translating or not self.source:
            return
        if len(self.source) > 1000 and not self.knobs.get("fast"):
            self.translating, self.status = True, ""
        else:
            self.result, self.status = TRANSLATION, ""

    def _activate(self, node: Node, key: str) -> None:
        if node.control_type == "CheckBox" and node.name in self.voices:
            if key == "space" and not self.knobs.get("space_ignored"):
                self.voices[node.name] ^= True
        elif node.name in OPENS and not (key == "enter" and self.knobs.get("enter_ignored")):
            self.dialog, self.back, self.focus = OPENS[node.name], self.focus, -1
        elif node.name == "Yes":
            self.removed = True
        elif node.name == s.TEXT_TRANSLATE:
            self._translate()

    def _type(self, text: str) -> None:
        self.source = text if self.selected_all else self.source + text
        self.selected_all = False

    def _key(self, token: str) -> None:
        node, k = self.focused(), self.knobs
        in_source = node is not None and node.name == s.TEXT_SOURCE_LABEL
        if token == "{TAB}":
            stops = self._stops()
            self.focus = (self.focus + 1) % len(stops)
        elif token in ("{SPACE}", "{ENTER}") and not in_source:
            if node is not None:
                self._activate(node, token[1:-1].lower())
        elif token == "{ESC}":
            if self.dialog is not None and not k.get("escape_ignored"):
                self.dialog, self.focus = None, self.back
            elif self.translating:
                self.translating, self.status = False, s.TEXT_CANCELLED
        elif token == "{F8}" and self.page == "Listen & translate" and not k.get("f8_ignored"):
            self.listening = True
        elif token == "{F9}":
            self.listening = False
        elif re.fullmatch(r"\^[1-7]", token) and token[1] not in k.get("ctrl_ignored", ""):
            self._show(SIDEBAR[int(token[1]) - 1][0])
        elif token == "^{ENTER}" and in_source:
            self._translate()
        elif in_source:
            self._edit(token)

    def _edit(self, token: str) -> None:
        if token == "^a":
            self.selected_all = True
        elif token == "^c":
            self.clipboard = self.source
        elif token == "^v":
            self._type(self.clipboard)
        elif token == "{END}":
            self.selected_all = False
        elif token == "{DELETE}" and self.selected_all:
            self._type("")
        elif token == "{ENTER}":
            self._type("\n")
        elif len(token) == 3 and token[0] == "{":
            self._type(token[1])
        elif len(token) == 1:
            self._type(token)

    def keys(self, text: str) -> None:
        for token in _TOKEN.findall(text):
            self._key(token)

    send = keys  # the fake has no main window to bring to the front
