"""Unit tests of the spoken-output row E-15 with a faked window, cable and log (CAP-0167 AC-25).

E-15 passes only when the cable is Microphone and Speakers, every voice switch is on, the
turn is shown and spoken, F9 during playback ends the session and the playback, and the
phrase played again starts no capture and changes no transcript. The fake app writes the
event lines the real app logs; the last test pins those lines to the app's source.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from native_e2e.evidence.model import Method, Status
from native_e2e.rows import e15
from tests._native_fake_app import CABLE, FakeApp, install, make_ctx

ROOT = Path(__file__).resolve().parents[1]
PAUSED = "Microphone paused while the translation is spoken"


class SpeakingApp(FakeApp):
    """``FakeApp`` plus Speakers, the paused state, **Stop playback** and the app log."""

    def __init__(self, **knobs) -> None:
        super().__init__(**knobs)
        self.voices = dict.fromkeys(self.voices, False)  # E-03 left both switches off
        self.speakers, self.speaking = "Follow Windows default", False

    def write(self, line: str) -> None:
        path = e15.log_path(self.ctx)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log:
            log.write(f"2026-11-24 10:00:00 | INFO | lianiq | {line}\n")

    def _conversation(self, top):
        nodes = [
            dataclasses.replace(n, enabled=False)
            if n.control_type == "CheckBox" and self.knobs.get("voice_missing")
            else n
            for n in super()._conversation(top)
        ]
        state = PAUSED if self.speaking else ("Listening …" if self.running else "Ready")
        return [
            *nodes,
            dataclasses.replace(nodes[0], name=state, control_type="Text"),
            dataclasses.replace(nodes[0], name="Stop playback", enabled=self.speaking),
        ]

    def _settings(self, top):
        speakers = dataclasses.replace(super()._settings(top)[0], value=self.speakers)
        return [*super()._settings(top), dataclasses.replace(speakers, name="Speakers")]

    def choose(self, node, item: str) -> None:
        if node.name != "Speakers":
            return super().choose(node, item)
        if self.knobs.get("no_speakers_item"):
            raise IndexError("item not found")
        self.speakers = item

    def keys(self, text: str) -> None:
        was_running = self.running
        super().keys(text)
        if text == "{F8}" and self.running:
            self.write("Microphone capture started (48000 Hz)")
        elif text == "{F9}" and was_running and not self.running:
            self.write("Microphone capture stopped")
            if self.speaking and not self.knobs.get("played_through"):
                self.write("Audio playback stopped: language=zh-Hans")
            self.speaking = False

    def hear_phrase(self) -> None:
        if not self.running:
            if self.knobs.get("capture_after_stop"):
                self.write("Microphone capture started (48000 Hz)")
            return
        super().hear_phrase()
        if not any(self.voices.values()) or self.knobs.get("no_speech"):
            return
        self.write("Speech synthesis completed in 0.400 seconds: language=zh-Hans options=-")
        if self.knobs.get("played_through"):
            self.write("Audio playback completed: language=zh-Hans")
        self.speaking = True


@pytest.fixture
def ctx(tmp_path):
    return make_ctx(tmp_path)


def run_e15(ctx, monkeypatch, **knobs):
    app = SpeakingApp(**knobs)
    install(monkeypatch, app)
    return e15.run(ctx), app


def failed(row) -> list[str]:
    return [check.name for check in row.checks if check.result is not Status.PASS]


def test_e15_passes_with_one_spoken_turn_stopped_during_playback(ctx, monkeypatch) -> None:
    row, app = run_e15(ctx, monkeypatch)
    assert row.status is Status.PASS, row.checks
    assert row.method is Method.VIRTUAL_DEVICE and row.acs == ("AC-25",)
    assert [check.name for check in row.checks] == [
        "test-phrase-sha256",
        "microphone-cable-selected",
        "speakers-cable-selected",
        "voice-output-on",
        "session-running",
        "translation-spoken",
        "stopped-with-f9-during-playback",
        "playback-ended-by-stop",
        "no-capture-after-stop",
        "transcript-sha256-unchanged",
        "screenshot-after-stop-masked",
    ]
    assert app.speakers == CABLE and all(app.voices.values())
    assert app.closed and "app" not in ctx.state
    assert [a.path for a in row.artifacts] == ["screens/e15-after-stop.png"]
    text = json.dumps(row.to_dict(), ensure_ascii=False)
    assert "Guten Morgen" not in text and "Microphone capture" not in text
    assert any("Guten Morgen" in secret for secret in ctx.secrets)  # the scan finds a leak


@pytest.mark.parametrize(
    ("knobs", "check"),
    [
        ({"no_speakers_item": True}, "speakers-cable-selected"),
        ({"voice_missing": True}, "voice-output-on"),
        ({"no_speech": True}, "translation-spoken"),
        ({"f9_ignored": True}, "stopped-with-f9-during-playback"),
        ({"played_through": True}, "playback-ended-by-stop"),
        ({"capture_after_stop": True}, "no-capture-after-stop"),
    ],
)
def test_e15_fails_when_a_pass_rule_does_not_hold(ctx, monkeypatch, knobs, check) -> None:
    row, app = run_e15(ctx, monkeypatch, **knobs)
    assert row.status is Status.FAIL and check in failed(row)
    assert app.closed


def test_e15_checks_the_phrase_before_any_app_starts(ctx, monkeypatch) -> None:
    image = json.loads((ctx.image_root / "image.json").read_text(encoding="utf-8"))
    image["test_phrase"]["sha256"] = "0" * 64
    (ctx.image_root / "image.json").write_text(json.dumps(image), encoding="utf-8")
    row, app = run_e15(ctx, monkeypatch)
    assert failed(row) == ["test-phrase-sha256"] and app.launches == 0


def test_the_log_lines_e15_reads_are_the_ones_the_app_writes() -> None:
    capture = (ROOT / "lianiq" / "audio" / "capture.py").read_text(encoding="utf-8")
    spoken = (ROOT / "lianiq" / "conversation" / "spoken_output.py").read_text(encoding="utf-8")
    assert e15.CAPTURE_STARTED in capture and e15.CAPTURE_STOPPED in capture
    assert e15.SYNTHESIZED in spoken
    assert "Audio playback %s" in spoken and '"stopped" if cancel.is_set()' in spoken
    assert e15.PLAYBACK_STOPPED[1] in spoken
