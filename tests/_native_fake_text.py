"""A scripted Text translation window with the setup assistant (rows E-20..E-23, CAP-0172).

The real window, folder picker and cable exist only in the VM. The fake models the sidebar,
the assistant steps, the Text translation page, Settings' device combos, F8/F9 and the
strip; ``install`` routes launch, scratch models, import, cable, clipboard and export to it.
Knobs: ``no_get`` (no readiness Get…), ``no_stale`` (an edit keeps the result current).
"""

from __future__ import annotations

import json
from contextlib import contextmanager

from native_e2e.uia import Node

CABLE_IN, CABLE_OUT = (
    "CABLE Input (VB-Audio Virtual Cable)",
    "CABLE Output (VB-Audio Virtual Cable)",
)
ENTRIES = ("Conversation", "Text translation", "Language packs", "Settings")
DE, ZH = "German", "Mandarin (Simplified)"
STEPS = ("What do you want to do?", "Conversation languages", "Audio check", "Readiness")
EDGES = {"mt-de-zh-hans": (DE, ZH), "mt-zh-hans-de": (ZH, DE)}
VOICES = {"tts-de-thorsten-medium": DE, "tts-zh-hans-aishell3": ZH}


class FakeText:
    rect = (100, 100, 900, 700)

    def __init__(self, scratch=None, **knobs) -> None:
        self.knobs, self.scratch = knobs, scratch
        self.packs: set[str] = set(knobs.get("packs", ()))
        self.closed, self.launches, self.clipboard = True, 0, None
        self.devices = {"Speakers": "Follow Windows default", "Microphone": "Follow default"}
        self.notices: list[str] = []
        self.start(None)
        self.launches = 0

    def start(self, ctx, setup_assistant: bool = False):
        self.launches += 1
        self.closed, self.page, self.step = False, "Conversation", 0 if setup_assistant else None
        self.usage = {"Conversation": True, "Text translation": False}
        self.lang = [DE, ZH]
        self.source, self.target, self.text, self.result = DE, ZH, "", ""
        self.current = self.playing = self.replay = self.conversation = False
        self.dialog = self.dialog_pack = None
        self.ends = 0  # node reads left before a Replay ends by itself
        return self

    def close(self) -> int:
        self.closed = True
        return 0

    # What UI Automation reads

    def nodes(self) -> list[Node]:
        if self.playing and self.ends:
            self.ends -= 1
            self.playing = self.ends > 0
        out = [
            Node(n, "CheckBox", selected=n == self.page, parents=("Workspaces",)) for n in ENTRIES
        ]
        if self.playing or self.conversation:
            mode = "Text translation" if self.playing else "Conversation"
            out += [Node("Active session", "Group"), Node(f"{mode} running", "Text")]
        out += [Node(title, "Text") for title in self.notices[-1:]]
        if self.page == "Settings":
            out += [Node(k, "ComboBox", value=v) for k, v in self.devices.items()]
        if self.page == "Text translation":
            out += self._text_page()
        return out

    def _ready(self) -> bool:
        return any(EDGES[p] == (self.source, self.target) for p in self.packs if p in EDGES)

    def _text_page(self) -> list[Node]:
        too_long = len(self.text) > 50000
        voice = any(VOICES.get(p) == self.target for p in self.packs)
        stale = bool(self.result) and not self.current
        label = "Stop" if self.playing else "Replay" if self.replay else "Play translation"
        out = [
            Node("Source language", "ComboBox", value=self.source),
            Node("Target language", "ComboBox", value=self.target),
            Node("Swap languages", "Button"),
            Node("Source text", "Text"),
            Node("Source text", "Edit", value=self.text, rect=(120, 200, 480, 600)),
            Node("Translation", "Text"),
            Node("Translation", "Edit", value=self.result, rect=(500, 200, 880, 600)),
            Node("Translate", "Button", enabled=bool(self.text) and not too_long and self._ready()),
            Node("Copy translation", "Button", enabled=self.current),
            Node(label, "Button", enabled=self.playing or (self.current and voice)),
        ]
        if stale:
            out.append(
                Node("Out of date — the text or a language changed. Translate again.", "Text")
            )
        if too_long:
            limit = "Shorten the text to 50000 characters."
            out.append(Node(f"Too long to translate: {len(self.text)} characters. {limit}", "Text"))
        if not voice:
            out += [
                Node(f"Play translation needs the {self.target} voice.", "Text"),
                Node("Open Language packs", "Button"),
            ]
        return out

    def window_nodes(self, title: str):
        if title == "Set up Lianiq" and self.step is not None:
            return self._assistant()
        if self.dialog is not None and title == self.dialog:
            return [Node(title, "Window")]
        return None

    def _assistant(self) -> list[Node]:
        from native_e2e.rows import text_flow

        out = [
            Node(STEPS[self.step], "Text"),
            Node("Next" if self.step < 3 else "Finish", "Button"),
        ]
        if self.step == 0:
            out += [Node(n, "CheckBox", selected=on) for n, on in self.usage.items()]
        elif self.step == 1:
            for owner, chosen in zip(("First language", "Second language"), self.lang):
                out += [
                    Node(n, "ListItem", selected=n == chosen, parents=(owner,)) for n in (DE, ZH)
                ]
        elif self.step == 3:
            for pack_id in EDGES:
                state = "Ready" if pack_id in self.packs else "Not installed"
                row = f"{text_flow.label('translation', pack_id)} — {state} — Needed by: Text translation"
                out.append(Node(row, "Text"))
                if state != "Ready" and not self.knobs.get("no_get"):
                    out.append(Node("Get…", "Button", description=row))
            for lang in ("de", "zh-Hans"):
                row = f"{text_flow.label('voice', lang)} — Not installed — Optional — for spoken output"
                out.append(Node(row, "Text"))
        return out

    # Actions

    def press(self, node: Node) -> None:
        name = node.name
        if "Workspaces" in node.parents:
            self.page = name
        elif self.step is not None:
            self._assistant_press(node)
        elif name == "Translate":
            self.result, self.current = f"译文{len(self.text)}{self.target[:2]}", True
        elif name == "Swap languages":
            self.source, self.target, self.current = self.target, self.source, False
        elif name == "Copy translation":
            self.clipboard = self.result
        elif name in ("Play translation", "Replay"):
            if self.conversation:
                self.notices.append("Stop the Conversation session first")
            else:
                self.playing, self.ends = True, 3 if name == "Replay" else 0
        elif name == "Stop":
            self.playing, self.replay = False, True

    def _assistant_press(self, node: Node) -> None:
        if node.name == "Next":
            self.step += 1
        elif node.name == "Finish":
            self.step = None
        elif node.control_type == "CheckBox":
            self.usage[node.name] = not node.selected
        elif node.control_type == "ListItem":
            self.lang[0 if "First language" in node.parents else 1] = node.name
        elif node.name == "Get…":
            from native_e2e import packs_import

            self.dialog_pack = next(p for p in EDGES if node.description.startswith(_lead(p)))
            self.dialog = packs_import.pack(self.dialog_pack).model

    def finish_dialog(self) -> None:
        """The pack dialog's licence and import steps (faked ``packs_import`` steps)."""
        self.install_pack(self.dialog_pack)
        self.dialog = self.dialog_pack = None

    def install_pack(self, pack_id: str) -> None:
        self.packs.add(pack_id)
        if self.scratch is not None:
            records = [{"id": p} for p in sorted(self.packs)]
            (self.scratch / "model-manifest.json").write_text(json.dumps({"packs": records}))

    def keys(self, text: str) -> None:
        if text == "{F8}" and self.page == "Conversation":
            self.conversation = True
        elif text == "{F9}":
            if self.playing:
                self.playing, self.replay = False, True
            self.conversation = False
        elif text == "{BACKSPACE}":
            self.text = self.text[:-1]
        elif text == "^a^v":
            self.text = self.clipboard or ""
        elif text == "^{END}x":
            self.text += "x"
        elif text.startswith("^a{DELETE}"):
            body = text.removeprefix("^a{DELETE}").replace("{ENTER}", "\n")
            for char in "+^%~(){}[]":
                body = body.replace("{" + char + "}", char)
            self.text = body
        else:
            return
        if text != "{F8}" and text != "{F9}" and not self.knobs.get("no_stale"):
            self.current = False

    def choose(self, node: Node, item: str) -> None:
        if node.name in self.devices:
            self.devices[node.name] = item
        elif node.name == "Target language" and item == self.source:
            self.source, self.target, self.current = self.target, self.source, False


def _lead(pack_id: str) -> str:
    from native_e2e.rows import text_flow

    return text_flow.label("translation", pack_id)


def install(monkeypatch, app: FakeText, tmp_path) -> dict:
    """Route launch, scratch models, import, cable, clipboard and export to ``app``."""
    from native_e2e import audio, models_swap, packs_import, screens, uia_app
    from native_e2e.rows import e10, e21, text_flow, ui
    from tests._native_png import red_png

    seen: dict = {"resets": 0, "scratch": []}

    @contextmanager
    def scratch(ctx, group):
        folder = tmp_path / f"models-{group}"
        folder.mkdir(exist_ok=True)
        app.scratch = folder
        seen["scratch"].append(group)
        yield folder

    def image_pack_dir(ctx, pack_id):
        folder = tmp_path / "image-packs" / pack_id
        folder.mkdir(parents=True, exist_ok=True)
        if not seen.get("no_pack_file"):
            (folder / packs_import.PACK_FILE).write_text("{}")
        return folder

    def import_folder(fake, pack_id, folder):
        app.install_pack(pack_id)
        return "validated"

    def export(fake, s, path, replace=False):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("diagnostics without the sentinel", encoding="utf-8")
        return True, False

    def reset(ctx):
        seen["resets"] += 1
        return True

    monkeypatch.setattr(uia_app, "launch", app.start)
    monkeypatch.setattr(uia_app, "settings_reset", reset)
    monkeypatch.setattr(models_swap, "scratch_models", scratch)
    monkeypatch.setattr(packs_import, "image_pack_dir", image_pack_dir)
    monkeypatch.setattr(packs_import, "import_folder", import_folder)
    monkeypatch.setattr(packs_import, "_accept_licence", lambda *a: None)
    monkeypatch.setattr(packs_import, "_choose_folder", lambda *a: app.finish_dialog())
    monkeypatch.setattr(e10, "export", export)
    monkeypatch.setattr(text_flow, "clipboard_text", lambda: app.clipboard)
    monkeypatch.setattr(text_flow, "set_clipboard", lambda t: setattr(app, "clipboard", t) or True)
    monkeypatch.setattr(screens, "grab", red_png)
    names = {"output": CABLE_IN, "input": CABLE_OUT}
    monkeypatch.setattr(audio, "wasapi_name", lambda prefix, kind: names[kind])
    monkeypatch.setattr(audio, "endpoint_names", lambda: [CABLE_IN, CABLE_OUT])
    monkeypatch.setattr(ui, "TIMEOUT_S", 0.3)
    monkeypatch.setattr(ui, "MODEL_TIMEOUT_S", 0.3)
    monkeypatch.setattr(ui, "POLL_S", 0.01)
    monkeypatch.setattr(e21, "STALE_S", 0.3)
    return seen
