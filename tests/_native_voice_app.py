"""The voice-output fake of the E-27..E-30 row tests (CAP-0167; ``test_native_rows_voice``).

The E-15 fake plus the voice row (switch states, **Replay**, **Stop playback**, **Voice
options…** dialogs, **Open Language packs**), the paused state, the level bar, the
Diagnostics readiness value and the app log lines of ``spoken_output.py``. A spoken turn
stays in the paused state for a few reads, then logs a completed playback. The cable
recorder returns a speech block as long as the replayed voice's rate allows.
"""

from __future__ import annotations

import json
import threading

import numpy

from native_e2e import audio, synth
from native_e2e.data import make_fixtures
from native_e2e.rows import e29, voice
from native_e2e.uia import Node
from tests._native_fake_app import install, make_ctx
from tests.test_native_rows_e15 import SpeakingApp

NAMES = {"de": "German", "zh-Hans": "Mandarin (Simplified)"}
RATE = 100  # fake cable sample rate


class VoiceApp(SpeakingApp):
    def __init__(self, **knobs) -> None:
        super().__init__(**knobs)
        self.voices = dict.fromkeys(self.voices, True)
        self.zh_missing = bool(knobs.get("zh_missing"))
        self.left = 0  # reads left until the current playback completes
        self.speaking_lang = self.last = None
        self.dialog_title = None
        self.rates = {"de": 1.0, "zh-Hans": 1.0}
        self.replay_s = 0.0

    # Reads -------------------------------------------------------------------------------

    def nodes(self):
        if self.speaking and self.left > 0:
            self.left -= 1
            if self.left == 0:
                self.write(f"Audio playback completed: language={self.speaking_lang}")
                self.speaking = False
        return super().nodes()

    def _voice(self, top, language: str) -> list[Node]:
        name = NAMES[language]
        missing = language == "zh-Hans" and self.zh_missing
        on = self.voices[f"Speak {name}"] and not missing
        state = "Voice missing" if missing else "Piper · Ready"
        action = f"Open Language packs for {name}" if missing else f"Voice options for {name}"
        return [
            Node(f"Speak {name}", "CheckBox", enabled=not missing, selected=on, parents=top),
            Node(f"{name} voice: {state}", "Text", parents=top),
            Node(action, "Button", parents=top),
        ]

    def _voice_rows(self, top) -> list[Node]:
        can = self.last is not None and not self.speaking and not self.knobs.get("no_replay")
        return [
            *self._voice(top, "de"),
            *self._voice(top, "zh-Hans"),
            Node("Voice output", "Group", parents=top),
            Node("Replay", "Button", enabled=can,
                 description="" if self.last else "Nothing to replay yet", parents=top),
            Node("Stop playback", "Button", enabled=self.speaking, parents=top),
        ]  # fmt: skip

    def _conversation(self, top):
        base = [n for n in super()._conversation(top) if n.control_type != "CheckBox"]
        base = [n for n in base if n.name != "Stop playback"]
        level = "35" if self.speaking and self.knobs.get("level_moves") else "0"
        return [*base, *self._voice_rows(top), Node("", "ProgressBar", value=level, parents=top)]

    def _settings(self, top):
        rows = [
            f"Voice {NAMES[lang]}: "
            + ("Voice missing" if lang == "zh-Hans" and self.zh_missing else "Ready")
            for lang in NAMES
        ]
        return [
            *super()._settings(top),
            *self._voice_rows(top),
            Node(
                "Call Bridge always speaks both languages and needs both voices. "
                "Meeting dual-mic needs the voice of the table language.",
                "Text",
                parents=top,
            ),
            Node("Readiness", "Text", value="\n".join(rows), parents=top),
        ]

    def window_nodes(self, title: str):
        if title != self.dialog_title:
            return None
        if "Mandarin" in title:
            rate = f"{self.rates['zh-Hans']:.2f}×"
            return [
                Node("Voice", "ComboBox"),
                Node("Rate", "Slider", description=rate),
                Node("Close", "Button"),
            ]
        return [Node("Rate", "Slider"), Node("Volume", "Slider"), Node("Close", "Button")]

    # Actions -----------------------------------------------------------------------------

    def _speak(self, language: str, reads: int | None = None) -> None:
        self.write(f"Speech synthesis completed in 0.400 seconds: language={language} options=-")
        self.speaking, self.speaking_lang, self.last = True, language, language
        self.left = reads if reads is not None else self.knobs.get("speak_reads", 2)

    def press(self, node: Node) -> None:
        if node.name.startswith("Voice options for "):
            self.dialog_title = "Voice options — " + node.name.removeprefix("Voice options for ")
        elif node.name == "Close":
            self.dialog_title = None
        elif node.name.startswith("Open Language packs for "):
            self.page = "Language packs"
        elif node.name == "Replay":
            factor = 1.0 if self.knobs.get("rate_ignored") else self.rates[self.last]
            self.replay_s = 2.0 / factor
            self._speak(self.last, 2)
        elif node.name == "Stop playback" and self.speaking:
            self.write(f"Audio playback stopped: language={self.speaking_lang}")
            self.speaking = False
        elif node.name.startswith("Speak ") and not node.enabled:
            return
        else:
            super().press(node)

    def set_value(self, node: Node, value: float) -> None:
        self.rates["zh-Hans"] = value / 100
        path = self.ctx.local_settings
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        data.setdefault("audio", {})
        data.setdefault("tts", {}).setdefault("output", {})["zh-Hans"] = {"rate": value / 100}
        path.write_text(json.dumps(data), encoding="utf-8")

    def hear(self, path) -> None:
        if not self.running:
            if self.knobs.get("capture_after_stop"):
                self.write("Microphone capture started (48000 Hz)")
            return
        mandarin = "zh" in path.name
        names = ("Mandarin (Simplified)", "German")
        source, target = names if mandarin else names[::-1]
        said = "你好，这是一个测试。" if mandarin else "Guten Morgen, das ist ein Test."
        heard = "Guten Morgen, das ist ein Test." if mandarin else "你好。"
        self.original += f"\n{source}: {said}"  # one more *Transcript* row
        self.translation += f"\n{target}: {heard}"
        target = "de" if mandarin else "zh-Hans"
        if target == "zh-Hans" and (self.zh_missing or self.knobs.get("zh_silent")):
            return
        self._speak(target)


class FakeRecorder:
    app: VoiceApp

    def start(self):
        self.t = 0.0
        return self

    def mark(self) -> float:
        self.t += 1.0
        return self.t

    def stop(self):
        samples = numpy.zeros(RATE * 20, dtype="float32")
        if self.app.knobs.get("late_signal"):
            samples[:] = 0.5
        elif self.app.replay_s:
            samples[10 : 10 + int(self.app.replay_s * RATE)] = 0.5
        return RATE, samples


def install_voice(monkeypatch, ctx, app: VoiceApp) -> None:
    install(monkeypatch, app)
    ctx.state["settings_backup"] = {"existed": False, "sha256": None, "path": None}
    FakeRecorder.app = app
    monkeypatch.setattr(audio, "CableRecorder", FakeRecorder)

    def play(path):
        app.hear(path)
        thread = threading.Thread(target=lambda: None)
        thread.start()
        return thread

    monkeypatch.setattr(voice, "play_async", play)
    monkeypatch.setattr(e29, "HOLD_S", 0.05)


def voice_ctx(tmp_path, monkeypatch):
    """A run context whose Mandarin fixture is a small local WAV (no synthesis)."""
    ctx = make_ctx(tmp_path)
    wav = tmp_path / "conv_zh_16k.wav"
    make_fixtures.write_wav(wav, b"\x01\x00" * 160)
    real = synth.speech_wav
    monkeypatch.setattr(
        synth, "speech_wav", lambda c, n: wav if n == "conv_zh_16k.wav" else real(c, n)
    )
    return ctx
