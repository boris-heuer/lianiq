"""A scripted stand-in for the real Lianiq window, as UI Automation would read it (CAP-0174).

pywinauto, the real window and the virtual cable exist only in the VM image, so the UIA row
tests drive this fake through the ``App`` surface the rows use. It models the sidebar, the
session strip, the Conversation panels, combos and Voice output, the Call Bridge Start,
Settings with the device combo, **Export…** and the notice history, the notice banner and
the export dialog with its "replace?" prompt. As in the real app (``_notice_changed``) every posted notice title is
logged into the history. Knobs remove elements or change behaviour, so each pass rule can
be shown to fail.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from native_e2e.uia import Node
from tests import _native_real_tree as real
from tests._native_png import red_png

CABLE = "CABLE Output (VB-Audio Virtual Cable)"
PLANNED = "Planned — not available yet"
SIDEBAR = (
    ("Conversation", True, ""),
    ("Meeting", True, ""),
    ("Text translation", False, PLANNED),
    ("Listen & translate", False, PLANNED),
    ("Call Bridge", True, "Experimental"),
    ("Language packs", False, PLANNED),
    ("Settings", True, ""),
)
ORIGINAL = "German: Guten Morgen, das ist ein Test."
TRANSLATION = "Mandarin (Simplified): 早上好，这是一个测试。"
WINDOW = (100, 100, 900, 700)
NOTICE_RECT = (320, 110, 880, 150)
PANEL_RECTS = ((320, 300, 880, 400), (320, 420, 880, 520))
DEFAULT_MIC = "Follow Windows default (now: Microphone Array)"
COMBO_RECT = (320, 200, 700, 230)


class FakeProcess:
    def __init__(self, files=(), maps=()) -> None:
        self._files, self._maps = files, maps

    def open_files(self):
        return [SimpleNamespace(path=path) for path in self._files]

    def memory_maps(self):
        return [SimpleNamespace(path=path) for path in self._maps]


class FakeApp:
    rect = WINDOW

    def __init__(self, **knobs) -> None:
        self.knobs = knobs
        self.missing: set[str] = set(knobs.get("missing", ()))
        self.extra: list[Node] = list(knobs.get("extra", ()))
        self.page = "Conversation"
        self.running = False
        self.original = self.translation = ""
        self.notices: list[str] = []
        self.log = "2026-11-14T10:00:00+01:00 [session] Conversation started\n"
        self.dialog, self.prompt = False, None
        self.mic, self.voice = DEFAULT_MIC, True
        self.readonly: set[Path] = set()
        self.closed = False
        self.launches = 0
        self.ctx = None
        self.process_list = [FakeProcess(**knobs.get("process", {}))]
        if knobs.get("no_processes"):
            self.process_list = []

    # Launch and close ------------------------------------------------------------------------

    def start(self, ctx):
        self.ctx, self.closed, self.page = ctx, False, "Conversation"
        self.launches += 1
        settings = ctx.local_settings
        if settings.is_file():
            audio = json.loads(settings.read_text(encoding="utf-8")).get("audio", {})
            legacy = audio.get("input_device") is not None and audio.get("input_policy") is None
            if legacy and not self.knobs.get("no_notice"):
                name = self.knobs.get("migrated_name", CABLE)
                title = f"Microphone set to '{name}' from your previous settings"
                self.post(title, "device.microphone-migrated")
        return self

    def close(self) -> int:
        self.closed, self.dialog_at_close = True, self.dialog
        settings = self.ctx.local_settings if self.ctx else None
        if settings is not None and settings.is_file() and not self.knobs.get("keep_index"):
            data = json.loads(settings.read_text(encoding="utf-8"))
            data["audio"].update(
                input_device=None,
                input_policy="explicit",
                input_endpoint_id="windows-mmdevice:v1:capture:{x}",
                input_device_name=CABLE,
                output_policy="follow_default",
            )
            settings.write_text(json.dumps(data), encoding="utf-8")
        return 0

    def post(self, title: str, key: str, severity: str = "info") -> None:
        self.notices.append(title)
        self.log += f"2026-11-14T10:02:00+01:00 [notice] {severity} {key}: {title}\n"

    def processes(self):
        return self.process_list

    # What UI Automation reads ----------------------------------------------------------------

    def nodes(self) -> list[Node]:
        top = ("lianiq",)
        order = self.knobs.get("sidebar", SIDEBAR)
        out = [
            Node(
                label,
                real.NAV_ENTRY,
                enabled=enabled,
                selected=label == self.page,
                description=desc,
                rect=(100, 110 + 40 * i, 300, 140 + 40 * i),
                parents=(*top, "Workspaces"),
            )
            for i, (label, enabled, desc) in enumerate(order)
        ]
        if self.running:
            out += [
                Node("Active session", "Group", description="Conversation running", parents=top),
                Node("Conversation running", "Text", parents=(*top, "Active session")),
                Node("Stop (F9)", "Button", parents=(*top, "Active session")),
            ]
        if self.notices:
            title = self.notices[-1]
            out += [
                Node(f"Information: {title}", "Group", rect=NOTICE_RECT, parents=top),
                Node(title, "Text", rect=NOTICE_RECT, parents=(*top, "Notices")),
            ]
        out += getattr(self, f"_{self.page.split()[0].lower()}", lambda _: [])(top)
        out += self.extra
        return [node for node in out if node.name not in self.missing]

    def _conversation(self, top) -> list[Node]:
        back = bool(self.original) and not self.running
        on = {k for k in ("changed", "scroll", "pair", "direction") if self.knobs.get(k)}
        on = on if back else set()
        pair = "German ↔ English" if "pair" in on else "German ↔ Mandarin (Simplified)"
        way = "German → Mandarin" if "direction" in on else "Automatic"
        return [
            Node("▶  Start  (F8)", "Button", parents=top),
            Node("Voice output", "CheckBox", selected=self.voice, parents=top),
            Node("Language pair", "ComboBox", value=pair, parents=top),
            Node("Conversation direction", "ComboBox", value=way, parents=top),
            Node("Original", "Text", parents=top),
            Node("Original", "Edit", value=self.original + (" x" if "changed" in on else ""),
                 rect=PANEL_RECTS[0], parents=top),
            Node("Translation", "Text", parents=top),
            Node("Translation", "Edit", value=self.translation, rect=PANEL_RECTS[1],
                 parents=top),
            *real.panel_bars(top, bool(self.knobs.get("no_scroll")), "scroll" in on),
        ]  # fmt: skip

    def _call(self, top) -> list[Node]:
        busy = self.running and not self.knobs.get("bridge_start_enabled")
        description = "Stop the Conversation session first" if busy else ""
        return [Node("Start call bridge", "Button", enabled=not busy, description=description)]

    def _settings(self, top) -> list[Node]:
        return [
            Node("Microphone", "ComboBox", value=self.mic, rect=COMBO_RECT, parents=top),
            Node("Export…", "Button", parents=top),
            *real.history(top, self.log),
        ]

    # Actions -------------------------------------------------------------------------------

    def press(self, node: Node) -> None:
        if "Workspaces" in node.parents and node.enabled:
            self.page = node.name
        elif node.name == "Export…":
            self.dialog = True
        elif node.name == "Cancel":
            self.dialog = False
        elif node.automation_id == "CommandButton_6" and self.prompt:
            path, self.prompt = self.prompt, None
            self.save(path)
        elif node.name == "Voice output" and not self.knobs.get("voice_stuck"):
            self.voice = not self.voice

    def choose(self, node: Node, item: str) -> None:
        if node.name != "Microphone" or self.knobs.get("no_cable_item") or item != CABLE:
            raise IndexError("item not found")
        if not self.knobs.get("mic_ignored"):
            self.mic = item

    def keys(self, text: str) -> None:
        if text == "{F8}" and self.page == "Conversation":
            self.running = True
        elif text == "{F9}" and not self.knobs.get("f9_ignored"):
            self.running = False

    def hear_phrase(self) -> None:
        if self.running and not self.knobs.get("no_turn"):
            self.original, self.translation = ORIGINAL, TRANSLATION

    def window_nodes(self, title: str) -> list[Node] | None:
        if not self.dialog or title != "Export diagnostics":
            return None
        return [*real.SAVE_DIALOG, *(real.REPLACE_PROMPT if self.prompt else ())]

    def type_into(self, node: Node, text: str) -> None:
        assert (node.control_type, node.automation_id) == ("Edit", "1001")
        path = Path(text)
        if path in self.readonly and not self.knobs.get("no_prompt"):
            self.prompt = path  # "already exists, replace?"
        else:
            self.save(path)

    def save(self, path: Path) -> None:
        if path in self.readonly and self.knobs.get("dialog_stuck"):
            return  # e.g. an error box over the dialog: nothing happens
        self.dialog = False
        if path in self.readonly and not self.knobs.get("ro_writable"):
            self.log += "2026-11-14T10:01:00+01:00 [export] Diagnostics export failed\n"
            self.log += "2026-11-14T10:01:00+01:00 [notice] resolved settings.export-result\n"
            failure = self.knobs.get("failure", "Export failed: Permission denied.")
            self.post(failure, "settings.export-failed", "warning")
            return
        content = self.log + self.knobs.get("leak", "")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.post(f"Diagnostics saved as '{path.name}'.", "settings.export-result")


def make_ctx(tmp_path: Path, phrase: bytes = b"RIFF\x00\x00\x00\x00WAVEfake"):
    import hashlib

    from native_e2e.context import RunContext

    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    root = tmp_path / "image"
    (root / "state").mkdir(parents=True)
    wav = root / "test-phrase.wav"
    wav.write_bytes(phrase)
    image = {
        "image": "win11-native-e2e@20261113",
        "models_dir": str(tmp_path / "store" / "models"),
        "test_phrase": {"path": str(wav), "sha256": hashlib.sha256(phrase).hexdigest()},
    }
    (root / "image.json").write_text(json.dumps(image), encoding="utf-8")
    return RunContext(
        commit="a" * 40, out=tmp_path / "out", repo=repo, image_root=root, temp=tmp_path / "temp"
    )


def install(monkeypatch, app: FakeApp) -> None:
    """Route the rows' window, screen, cable and ACL calls to ``app`` and short timeouts."""
    from native_e2e import audio, screens, uia_app
    from native_e2e.rows import e10, ui

    monkeypatch.setattr(uia_app, "launch", app.start)
    monkeypatch.setattr(screens, "grab", red_png)
    monkeypatch.setattr(audio, "legacy_input_index", lambda: 7)
    monkeypatch.setattr(audio, "wasapi_name", lambda prefix, kind: CABLE)
    monkeypatch.setattr(audio, "play_into_cable", lambda path: app.hear_phrase())
    names = ["CABLE Input (VB-Audio Virtual Cable)", CABLE]
    monkeypatch.setattr(audio, "endpoint_names", lambda: names)
    ids = ["windows-mmdevice:v1:capture:{abc-123}", "{abc-123}"]
    monkeypatch.setattr(audio, "cable_endpoint_ids", lambda: ids)

    def protect(path: Path) -> bool:  # E-10's protected file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(e10.PROTECTED_CONTENT, encoding="utf-8")
        return app.readonly.add(path) or True

    monkeypatch.setattr(e10, "deny_write", protect)
    monkeypatch.setattr(ui, "TIMEOUT_S", 0.3)
    monkeypatch.setattr(ui, "MODEL_TIMEOUT_S", 0.3)
    monkeypatch.setattr(ui, "POLL_S", 0.01)
