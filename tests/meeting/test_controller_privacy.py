"""Meeting privacy and offline guarantees (CAP-0177 WI-03; AC-17 and AC-18).

AC-17 Integration: a full meeting writes no file at all while it runs, not even a temporary
one (speech is synthesised and played in memory; captured audio is never written): every
file-writing entry point fails the test. Its log records carry no recognised or translated
text and no PCM. AC-17 Static check: no module of ``lianiq/meeting/`` writes audio, uses a
temporary file (except the consented transcript write) or passes text or samples to a log.
AC-18 Integration (socket guard): a full meeting completes without any network attempt.
"""

from __future__ import annotations

import ast
import builtins
import io
import logging
import os
import socket
import tempfile
import wave
from pathlib import Path

import numpy as np
import pytest

from lianiq.meeting import MeetingRole
from lianiq.meeting.controller import MeetingEventKind as Kind
from tests.meeting.support import DE, ZH, Line, say, wait_until

TABLE, USER = MeetingRole.TABLE_CAPTURE, MeetingRole.USER_CAPTURE
PACKAGE = Path(__file__).resolve().parents[2] / "lianiq" / "meeting"
SECRET = {10: Line(ZH, "机密报价"), 20: Line(DE, "Vertraulicher Preis"), 11: Line(DE, "Geheim")}
AUDIO_WRITERS = {"wave", "soundfile", "scipy", "pydub", "audioread"}
SENSITIVE = {"text", "translated", "transcript", "samples", "utterance", "frame", "line", "audio"}
SENSITIVE |= {"source_text", "translated_text", "output", "item", "result", "detection"}
LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical", "log"}


WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
TEMP_FACTORIES = ("NamedTemporaryFile", "TemporaryFile", "SpooledTemporaryFile", "mkstemp")


def forbid_file_writes(monkeypatch) -> list[tuple]:
    """From now on every file write or temporary file is recorded and fails."""
    attempts: list[tuple] = []
    real_open, real_os_open, real_wave_open = builtins.open, os.open, wave.open

    def refuse(*detail):
        attempts.append(detail)
        raise AssertionError(f"file write during the meeting: {detail}")

    def guarded_open(file, mode="r", *args, **kwargs):
        if isinstance(file, int) or any(flag in mode for flag in "wax+"):
            refuse("open", str(file), mode)
        return real_open(file, mode, *args, **kwargs)

    def guarded_os_open(path, flags, *args, **kwargs):
        if flags & WRITE_FLAGS:
            refuse("os.open", str(path))
        return real_os_open(path, flags, *args, **kwargs)

    def guarded_wave_open(target, mode=None):
        if mode is not None and mode.startswith("w"):
            refuse("wave.open", str(target), mode)
        return real_wave_open(target, mode)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(io, "open", guarded_open)
    monkeypatch.setattr(os, "open", guarded_os_open)
    monkeypatch.setattr(wave, "open", guarded_wave_open)
    for name in (*TEMP_FACTORIES, "mkdtemp"):
        monkeypatch.setattr(tempfile, name, lambda *a, name=name, **k: refuse(f"tempfile.{name}"))
    return attempts


def run_full_meeting(meeting, before_start=None, **options):
    harness = meeting(SECRET, speak_local=True, **options)
    controller = harness.controller
    if before_start is not None:
        before_start(harness)
    controller.start()
    for role, tag in ((TABLE, 10), (USER, 20), (TABLE, 11)):
        say(controller, role, tag)
    assert wait_until(lambda: len(harness.recognizer.calls) == 3)
    assert controller.stop(timeout=10.0)
    return harness


def test_ac17_a_meeting_writes_no_file_and_logs_no_text_or_pcm(
    meeting, tmp_path, monkeypatch, caplog
) -> None:
    """AC-17 (Integration): no audio file anywhere (temp folders included), no text in logs."""
    caplog.set_level(logging.DEBUG)
    attempts: list[tuple] = []
    harness = run_full_meeting(
        meeting, before_start=lambda _h: attempts.extend([forbid_file_writes(monkeypatch)])
    )
    monkeypatch.undo()

    assert attempts == [[]]  # no write, no temporary file, no WAV while the meeting ran
    assert len(harness.controller.results) == 2 and len(harness.renders.played) == 2
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []
    secrets = [line.text for line in SECRET.values()]
    secrets += [
        f"[{e}] {t}" for e, t in (("zh-Hans>de", "机密报价"), ("de>zh-Hans", "Vertraulicher Preis"))
    ]
    for record in caplog.records:
        message = record.getMessage()
        assert not any(secret in message for secret in secrets), message
        assert not any(isinstance(arg, np.ndarray) for arg in record.args or ())
    assert any(record.name.startswith("lianiq.meeting") for record in caplog.records)


def _calls(tree: ast.AST):
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call)]


def _names(node: ast.AST) -> set[str]:
    found = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            found.add(child.id)
        elif isinstance(child, ast.Attribute):
            found.add(child.attr)
    return found


def _logged(node: ast.AST) -> set[str]:
    """The identifiers a log argument shows: ``item.role.value`` shows ``value`` only."""
    if isinstance(node, ast.Attribute):
        return {node.attr}
    if isinstance(node, ast.Name):
        return {node.id}
    return _names(node)


def static_findings(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    findings = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            modules = (
                [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module]
            )
            for module in modules:
                root = (module or "").split(".")[0]
                if root in AUDIO_WRITERS or (root == "tempfile" and path.name != "transcript.py"):
                    findings.append(f"{path.name}:{node.lineno} imports {module}")
    for call in _calls(tree):
        func = call.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name in {"write_bytes", "tofile", "save", "savez", "wavfile", "synthesize"}:
            findings.append(f"{path.name}:{call.lineno} writes with {name}")
        if isinstance(func, ast.Attribute) and name in LOG_METHODS:
            target = _names(func.value)
            if target & {"LOGGER", "logging", "logger"}:
                if call.args and not isinstance(call.args[0], ast.Constant):
                    findings.append(f"{path.name}:{call.lineno} logs a non-constant message")
                for arg in [*call.args[1:], *(k.value for k in call.keywords)]:
                    leaked = _logged(arg) & SENSITIVE
                    if leaked:
                        findings.append(f"{path.name}:{call.lineno} logs {sorted(leaked)}")
    return findings


def test_ac17_static_check_no_audio_write_and_no_text_or_pcm_in_log_calls() -> None:
    """AC-17 (Static check): ``lianiq/meeting/`` writes no audio and logs no text or PCM."""
    files = sorted(PACKAGE.glob("*.py"))
    assert PACKAGE / "controller.py" in files and PACKAGE / "processing.py" in files
    assert [finding for path in files for finding in static_findings(path)] == []


def test_the_static_check_catches_an_audio_write_and_a_logged_text(tmp_path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text(
        "import wave\nimport tempfile\nLOGGER.info('Heard %s', transcript.text)\n"
        "LOGGER.info(f'{x}')\npath.write_bytes(b'')\ntts.synthesize('a', 'b')\n",
        encoding="utf-8",
    )
    assert len(static_findings(bad)) == 6


class TempWavSynthesizer:
    """A synthesiser that still writes a temporary WAV, as the file-based TTS path does."""

    def __init__(self, inner) -> None:
        self.inner, self.calls = inner, inner.calls

    def synthesize_pcm(self, text, language):
        with tempfile.NamedTemporaryFile(suffix=".wav"):
            return self.inner.synthesize_pcm(text, language)


def test_the_write_guard_catches_a_transient_temporary_wav(meeting, monkeypatch) -> None:
    attempts: list[list[tuple]] = []

    def swap(harness) -> None:
        harness.controller.engines = type(harness.controller.engines)(
            harness.recognizer, harness.translator, TempWavSynthesizer(harness.synthesizer)
        )
        attempts.append(forbid_file_writes(monkeypatch))

    run_full_meeting(meeting, before_start=swap)
    monkeypatch.undo()
    assert attempts[0] and attempts[0][0] == ("tempfile.NamedTemporaryFile",)
    forbid_file_writes(monkeypatch)
    with pytest.raises(AssertionError):
        tempfile.mkstemp()
    monkeypatch.undo()


def test_ac18_a_full_meeting_completes_without_any_network_attempt(meeting, monkeypatch) -> None:
    """AC-18 (Integration, socket guard): no network call is attempted."""
    attempts: list[tuple] = []

    def refuse(*args, **kwargs):
        attempts.append(args)
        raise AssertionError("network access")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    harness = run_full_meeting(meeting)

    assert attempts == []
    assert harness.events.items[-1].kind is Kind.STOPPED
    assert len(harness.controller.results) == 2
