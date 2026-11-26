"""The Listen & translate fake of the E-24..E-26 row tests (CAP-0170; ``test_native_rows_listen``).

It models what the rows read: the setup assistant (usage boxes, language lists, readiness
rows with **Get…**, **Finish**), the Listen page (combos, **Swap languages**, **Start
listening**, state, readiness text, *Transcript* rows, **Copy/Export transcript**), the
session strip, notices, Settings **Export…** and the app log under ``logs/lianiq.log``. The
pack dialogs are patched away (``assistant_import``, ``import_folder``); knobs make one pass
rule fail.
"""

from __future__ import annotations

from contextlib import contextmanager

from native_e2e import audio, audio_sessions, models_swap, packs_import, synth, uia_app
from native_e2e.data import make_fixtures
from native_e2e.rows import e25, e26
from native_e2e.rows import listen_flow as lf
from native_e2e.uia import Node
from tests import _native_real_tree as real
from tests._native_fake_app import CABLE, DEFAULT_MIC, SIDEBAR, install, make_ctx

TOP = ("lianiq",)
DE, ZH = "German", "Mandarin (Simplified)"
USAGES = ("Conversation", "Call Bridge (Experimental)", "Meeting dual-mic", "Text translation")
LISTEN = "Listen & translate"
REVIEW = {  # pack id → readiness row lead
    "stt-faster-whisper-small": f"Speech recognition {DE}, speech recognition {ZH}",
    "mt-de-zh-hans": f"Translation {DE} → {ZH}",
    "mt-zh-hans-de": f"Translation {ZH} → {DE}",
}
MISSING = f"Not available: missing translation {ZH} → {DE}"
SAYS = {
    "listen_de3_16k.wav": (
        "Guten Morgen.",
        "Wir liefern die Ware nächste Woche.",
        "Der Preis enthält die Fracht.",
    ),
    "conv_de_16k.wav": ("Guten Morgen, das ist ein Test.",),
    "listen_sentinel_16k.wav": ("Lianiq Kontrollsatz QX7 Hörprobe.",),
    "listen_zh_de_16k.wav": ("你好，很高兴见到你。", "Der Preis enthält die Fracht."),
}


class ListenFlowApp:
    rect = (100, 100, 900, 700)

    def __init__(self, **knobs) -> None:
        self.knobs, self.page, self.ctx, self.launches = knobs, "Conversation", None, 0
        self.installed: set[str] = set(knobs.get("installed", ()))
        self.assistant, self.step = False, 0
        self.ticks = dict.fromkeys((*USAGES, LISTEN), False) | {"Conversation": True}
        self.langs = {"First language": None, "Second language": None}
        self.values = {"Source language": DE, "Target language": ZH, "Microphone": DEFAULT_MIC}
        self.running, self.state, self.rows = False, "Ready", []
        self.notices: list[str] = []
        self.dialog = self.clipboard = None
        self.models = None
        self.closed = False

    def start(self, ctx, setup_assistant: bool = False):
        self.ctx, self.closed, self.page = ctx, False, "Conversation"
        self.launches += 1
        self.assistant, self.step = setup_assistant, 0
        self.rows, self.state = [], "Ready"
        return self

    def close(self) -> int:
        self.closed, self.running = True, False
        return 0

    def write(self, line: str) -> None:
        path = self.ctx.repo / "logs" / "lianiq.log"
        path.parent.mkdir(exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"2026-11-25T10:00:00+01:00 [listen] {line}\n")

    # Reads -------------------------------------------------------------------------------

    def ready(self) -> bool:
        edge = "mt-de-zh-hans" if self.values["Source language"] == DE else "mt-zh-hans-de"
        return {"stt-faster-whisper-small", edge} <= self.installed

    def nodes(self) -> list[Node]:
        out = [
            Node(label, real.NAV_ENTRY, enabled=on, selected=label == self.page, description=d,
                 rect=(100, 110 + 40 * i, 300, 140 + 40 * i), parents=(*TOP, "Workspaces"))
            for i, (label, on, d) in enumerate(SIDEBAR)
        ]  # fmt: skip
        if self.running:
            out.append(Node("Active session", "Group", description=f"{LISTEN} running"))
        out += [Node(title, "Text", parents=(*TOP, "Notices")) for title in self.notices[-1:]]
        if self.state == "Stopping…":
            self.state = "Stopped"  # one read shows "Stopping…"
            out.append(Node("Stopping…", "Text", parents=TOP))
        elif self.page == LISTEN:
            out += self._listen()
        elif self.page == "Settings":
            out.append(Node("Export…", "Button", parents=TOP))
        return out

    def _listen(self) -> list[Node]:
        idle, ready = not self.running, self.ready()
        state = "Listening…" if self.running else self.state
        out = [Node(k, "ComboBox", value=v, parents=TOP) for k, v in self.values.items()]
        out += [
            Node("Swap languages", "Button", enabled=idle, parents=TOP),
            Node("Start listening (F8)", "Button", enabled=idle and ready, parents=TOP),
            Node(state, "Text", parents=TOP),
            Node("Transcript", "List", parents=TOP),
            *(Node(t, "ListItem", parents=(*TOP, "Transcript")) for t in self.rows),
            Node("Copy transcript", "Button", enabled=bool(self.rows) and idle, parents=TOP),
            Node("Export transcript", "Button", enabled=bool(self.rows) and idle, parents=TOP),
        ]
        if idle and not ready:
            out += [Node(MISSING, "Text", parents=TOP), Node("Open Language packs", "Button")]
        return out

    def window_nodes(self, title: str) -> list[Node] | None:
        if title == "Set up Lianiq" and self.assistant:
            return self._assistant()
        if title == self.dialog:
            return [Node("File name:", "Edit", automation_id="1001")]
        return None

    def _assistant(self) -> list[Node]:
        titles = ("What do you want to do?", "Conversation languages", "Audio check", "Readiness")
        out = [Node(titles[self.step], "Text"), Node("Next", "Button", enabled=self.step < 3)]
        if self.step == 0:
            out += [Node(u, "CheckBox", selected=on) for u, on in self.ticks.items()]
        elif self.step == 1:
            for owner, chosen in self.langs.items():
                out += [
                    Node(n, "ListItem", selected=n == chosen, parents=(owner,)) for n in (DE, ZH)
                ]
        elif self.step == 3:
            out.append(Node("Finish", "Button"))
            out += self._review()
        return out

    def _review(self) -> list[Node]:
        out = []
        tail = f"Needed by: {LISTEN}"
        rows = [(pack, lead) for pack, lead in REVIEW.items()] + [(None, "Microphone")]
        if self.knobs.get("voice_row"):
            rows.append((None, "Voice German"))
        for pack, lead in rows:
            ready = pack is None or pack in self.installed
            text = f"{lead} — {'Ready' if ready else 'Not installed'} — {tail}"
            out.append(Node(text, "Text"))
            if not ready:
                out.append(Node("Get…", "Button", description=text))
        return out

    # Actions -----------------------------------------------------------------------------

    def press(self, node: Node) -> None:
        name = node.name
        if "Workspaces" in node.parents:
            self.page = name
        elif name == "Next":
            self.step += 1
        elif node.control_type == "CheckBox":
            self.ticks[name] = not self.ticks[name]
        elif node.control_type == "ListItem":
            self.langs[node.parents[0]] = name
        elif name == "Finish":
            self.assistant = False
            ids = ", ".join(f'{{"id": "{p}"}}' for p in sorted(self.installed))
            (self.models / "model-manifest.json").write_text(f'{{"packs": [{ids}]}}', "utf-8")
        elif name == "Start listening (F8)" and node.enabled:
            self.running = True
            self.write("Microphone capture started (16000 Hz)")
        elif name == "Swap languages":
            v = self.values
            v["Source language"], v["Target language"] = v["Target language"], v["Source language"]
        elif name == "Copy transcript":
            self.clipboard = self.transcript().replace("\n", "\r\n")
        elif name == "Export transcript":
            self.dialog = "Export transcript"
        elif name == "Export…":
            self.dialog = "Export diagnostics"

    def choose(self, node: Node, item: str) -> None:
        self.values[node.name] = item

    def keys(self, text: str) -> None:
        if text == "{F8}" and self.page == "Conversation" and self.running:
            self.notices.append(f"Stop the {LISTEN} session first")
        elif text == "{F9}" and self.running:
            self.running, self.state = False, "Stopping…"
            self.write("Microphone capture stopped")

    def type_into(self, node: Node, text: str) -> None:
        from pathlib import Path

        path, self.dialog = Path(text), None
        if path.name.startswith("listen"):
            path.write_text(self.transcript(), encoding="utf-8")
        else:
            path.write_text(self.ctx.repo.joinpath("logs", "lianiq.log").read_text("utf-8"))

    def hear(self, path) -> None:
        if not self.running:
            return
        mandarin = self.values["Source language"] == ZH
        src, tgt = (ZH, DE) if mandarin else (DE, ZH)
        for text in SAYS[path.name]:
            out = "Guten Tag." if mandarin else "早上好。"
            if mandarin and text.startswith("Der") and self.knobs.get("wrong_target"):
                self.rows.append(f"10:00:0{len(self.rows)}, {DE}: {text}. {ZH}: 价格。")
                continue
            self.rows.append(f"10:00:0{len(self.rows)}, {src}: {text}. {tgt}: {out}")
        if self.knobs.get("leak") and "sentinel" in path.name:
            self.write("segment: Lianiq Kontrollsatz QX7")

    def transcript(self) -> str:
        lines = ["# lianiq transcript v2", "# pair: de zh-Hans"]
        for row in self.rows:
            tag = "zh-Hans -> de" if f", {ZH}: " in row else "de -> zh-Hans"
            lines += ["", f"[2026-11-25T10:00:00+01:00] {tag}", "x: y", "x: y"]
        return "\n".join(lines) + "\n"

    def pids(self) -> list[int]:
        return [4242]


def install_listen(monkeypatch, tmp_path, app: ListenFlowApp):
    """A context, the fake app and every patched building block; returns the context."""
    ctx = make_ctx(tmp_path)
    install(monkeypatch, app)
    ctx.state["settings_backup"] = {"existed": False, "sha256": None, "path": None}
    monkeypatch.setattr(uia_app, "launch", app.start)
    monkeypatch.setattr(audio, "play_into_cable", app.hear)
    monkeypatch.setattr(audio_sessions, "render_pids", lambda: set())
    monkeypatch.setattr(lf, "SETTLE_S", 0.0)
    monkeypatch.setattr(e25, "clipboard_text", lambda: app.clipboard)
    monkeypatch.setattr(e26.tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    monkeypatch.setattr(packs_import, "has_pack_file", lambda folder: True)

    def assistant_import(a, s, pack_id, lead, folder):
        app.installed.add(pack_id)
        return "ready"

    monkeypatch.setattr(lf, "assistant_import", assistant_import)
    monkeypatch.setattr(
        packs_import, "import_folder", lambda a, p, f: app.installed.add(p) or "validated"
    )

    @contextmanager
    def scratch(c, group):
        app.models = c.temp / f"models-{group}"
        app.models.mkdir(parents=True, exist_ok=True)
        yield app.models

    monkeypatch.setattr(models_swap, "scratch_models", scratch)
    wav = tmp_path / "wav" / "listen_zh_de_16k.wav"
    wav.parent.mkdir()
    make_fixtures.write_wav(wav, b"\x01\x00" * 160)
    real_wav = synth.speech_wav
    monkeypatch.setattr(synth, "speech_wav", lambda c, n: wav if n == wav.name else real_wav(c, n))
    return ctx


__all__ = ["CABLE", "ListenFlowApp", "install_listen"]
