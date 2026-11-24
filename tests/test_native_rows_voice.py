"""Unit tests of the voice-output rows E-27..E-30 and ``synth`` (CAP-0167; spec §2.2).

The rows drive ``tests._native_voice_app.VoiceApp``; each pass rule has one test that shows
it can fail. ``synth`` prefers the pinned fixture, renders a missing one once per run from
the image models and gives ``None`` when the voice cannot render.
"""

from __future__ import annotations

import dataclasses
import json
from contextlib import contextmanager

import pytest

from native_e2e import fixtures, models_swap, packs_import, synth
from native_e2e.data import make_fixtures
from native_e2e.evidence.model import Status
from native_e2e.rows import e27, e28, e29, e30, voice
from native_e2e.uia import Node
from tests._native_fake_app import make_ctx
from tests._native_voice_app import NAMES, VoiceApp, install_voice, voice_ctx
from tests.test_native_rows_e15 import PAUSED


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    return voice_ctx(tmp_path, monkeypatch)


def failed(row) -> list[str]:
    return [check.name for check in row.checks if check.result is not Status.PASS]


# synth ---------------------------------------------------------------------------------


def test_synth_prefers_the_pinned_fixture_and_renders_a_missing_one_once(
    tmp_path, monkeypatch
) -> None:
    ctx = make_ctx(tmp_path)
    assert synth.speech_wav(ctx, "conv_de_16k.wav") == fixtures.checked("conv_de_16k.wav")
    calls = []

    def make(models, names, out):
        calls.append((models, names))
        make_fixtures.write_wav(out / names[0], b"\x01\x00" * 1600)

    monkeypatch.setattr(make_fixtures, "make", make)
    path = synth.speech_wav(ctx, "conv_zh_16k.wav")
    assert path == ctx.temp / "fixtures" / "conv_zh_16k.wav"
    assert synth.speech_wav(ctx, "conv_zh_16k.wav") == path and len(calls) == 1
    assert calls[0][0] == models_swap.image_models(ctx)
    assert (
        "你好，这是一个测试。" in ctx.secrets and "Guten Morgen, das ist ein Test." in ctx.secrets
    )


def test_synth_gives_none_when_the_voice_cannot_render(tmp_path, monkeypatch) -> None:
    ctx = make_ctx(tmp_path)

    def broken(models, names, out):
        raise FileNotFoundError("voice")

    monkeypatch.setattr(make_fixtures, "make", broken)
    assert synth.speech_wav(ctx, "listen_zh_de_16k.wav") is None
    assert synth.speech_wav(ctx, "no-such.wav") is None
    assert "你好，很高兴见到你。" in ctx.secrets  # the texts are secret before any synthesis


# E-27 ----------------------------------------------------------------------------------


def test_e27_passes_with_both_voices_ready(ctx, monkeypatch) -> None:
    app = VoiceApp()
    install_voice(monkeypatch, ctx, app)
    row = e27.run(ctx)
    assert row.status is Status.PASS, row.checks
    assert row.acs == ("AC-01", "AC-02", "AC-12", "AC-29") and app.closed


def test_e27_fails_with_the_mandarin_voice_missing(ctx, monkeypatch) -> None:
    install_voice(monkeypatch, ctx, VoiceApp(zh_missing=True))
    assert "switches-on-ready" in failed(e27.run(ctx))


# E-28 ----------------------------------------------------------------------------------


def test_e28_passes_and_stores_numbers_only(ctx, monkeypatch) -> None:
    app = VoiceApp()
    install_voice(monkeypatch, ctx, app)
    row = e28.run(ctx)
    assert row.status is Status.PASS, row.checks
    detail = next(c.detail for c in row.checks if c.name == "replay-faster-at-rate-1.30")
    assert detail == "first_s=2.0 second_s=1.54 ratio=0.77"
    assert not ctx.local_settings.exists()  # settings reset to the (absent) baseline
    text = json.dumps(row.to_dict(), ensure_ascii=False)
    assert "Guten Morgen" not in text and "你好" not in text


@pytest.mark.parametrize(
    ("knobs", "name"),
    [
        ({"rate_ignored": True}, "replay-faster-at-rate-1.30"),
        ({"level_moves": True}, "level-zero-during-speech"),
        ({"zh_silent": True}, "turns-spoken"),  # a turn never spoken times out
    ],
)
def test_e28_fails_when_a_pass_rule_does_not_hold(ctx, monkeypatch, knobs, name) -> None:
    install_voice(monkeypatch, ctx, VoiceApp(**knobs))
    assert name in failed(e28.run(ctx))


def test_e28_is_blocked_without_the_mandarin_fixture(ctx, monkeypatch) -> None:
    app = VoiceApp()
    install_voice(monkeypatch, ctx, app)
    monkeypatch.setattr(synth, "speech_wav", lambda c, n: None)
    row = e28.run(ctx)
    assert row.status is Status.BLOCKED and row.reason == "fixture-missing"
    assert app.launches == 0


# E-29 ----------------------------------------------------------------------------------


def test_e29_passes_when_both_stops_end_the_speech(ctx, monkeypatch) -> None:
    install_voice(monkeypatch, ctx, VoiceApp(speak_reads=10**6))
    row = e29.run(ctx)
    assert row.status is Status.PASS, row.checks
    assert ("last-signal-after-f9", "seconds=0.0") in [(c.name, c.detail) for c in row.checks]


@pytest.mark.parametrize(
    ("knobs", "name"),
    [
        ({"late_signal": True}, "last-signal-after-button"),
        ({"capture_after_stop": True}, "no-capture-after-f9"),
    ],
)
def test_e29_fails_when_a_pass_rule_does_not_hold(ctx, monkeypatch, knobs, name) -> None:
    install_voice(monkeypatch, ctx, VoiceApp(speak_reads=10**6, **knobs))
    assert name in failed(e29.run(ctx))


# E-30 ----------------------------------------------------------------------------------


def install_e30(monkeypatch, ctx, app: VoiceApp, result: str = "validated") -> list[str]:
    install_voice(monkeypatch, ctx, app)
    imported: list[str] = []

    @contextmanager
    def scratch(c, group):
        app.zh_missing = True
        try:
            yield c.temp / f"models-{group}"
        finally:
            app.zh_missing = False

    monkeypatch.setattr(models_swap, "scratch_models", scratch)
    monkeypatch.setattr(packs_import, "has_pack_file", lambda folder: True)
    monkeypatch.setattr(
        packs_import, "import_folder", lambda a, pack_id, f: imported.append(pack_id) or result
    )
    return imported


def test_e30_passes_with_the_mandarin_voice_missing_then_legacy_settings(ctx, monkeypatch) -> None:
    app = VoiceApp()
    imported = install_e30(monkeypatch, ctx, app)
    row = e30.run(ctx)
    assert row.status is Status.PASS, row.checks
    assert imported == e30.packs() and "tts-zh-hans-aishell3" not in imported
    assert sorted(imported) == [
        "mt-de-zh-hans", "mt-zh-hans-de", "stt-faster-whisper-small", "tts-de-thorsten-medium"
    ]  # fmt: skip
    assert app.launches == 2 and not ctx.local_settings.exists()


def test_e30_is_blocked_on_an_image_without_pack_files(ctx, monkeypatch) -> None:
    app = VoiceApp()
    install_e30(monkeypatch, ctx, app)
    monkeypatch.setattr(packs_import, "has_pack_file", lambda folder: False)
    row = e30.run(ctx)
    assert row.reason == "image-packs-without-pack-file" and app.launches == 0


def test_e30_needs_no_pack_file_in_the_folders_of_other_pairs(ctx, monkeypatch) -> None:
    app = VoiceApp()
    install_e30(monkeypatch, ctx, app)
    pair = {packs_import.image_pack_dir(ctx, p) for p in e30.packs()}
    monkeypatch.setattr(packs_import, "has_pack_file", lambda folder: folder in pair)
    row = e30.run(ctx)
    assert row.status is Status.PASS, row.checks


def test_e30_resets_settings_and_restores_models_when_the_group_raises(ctx, monkeypatch) -> None:
    app = VoiceApp()
    install_e30(monkeypatch, ctx, app)
    restored: list[bool] = []

    @contextmanager
    def scratch(c, group):
        try:
            yield c.temp
        finally:
            restored.append(True)

    def boom(a, pack_id, folder):
        raise RuntimeError("import")

    monkeypatch.setattr(models_swap, "scratch_models", scratch)
    monkeypatch.setattr(packs_import, "import_folder", boom)
    ctx.local_settings.write_text('{"audio": {}}', encoding="utf-8")
    with pytest.raises(RuntimeError):
        e30.run(ctx)
    assert restored == [True] and app.closed and not ctx.local_settings.exists()


def test_e30_fails_when_the_missing_voice_is_spoken(ctx, monkeypatch) -> None:
    app = VoiceApp()
    install_e30(monkeypatch, ctx, app)
    original = app.hear

    def hear(path):
        missing, app.zh_missing = app.zh_missing, False
        original(path)
        app.zh_missing = missing

    monkeypatch.setattr(app, "hear", hear)
    assert "german-spoken-mandarin-text-only" in failed(e30.run(ctx))


def test_the_voice_rows_read_the_app_strings() -> None:
    from lianiq.ui import strings

    assert voice.name("zh-Hans") == NAMES["zh-Hans"] and voice.name("de") == NAMES["de"]
    assert strings.VOICE_STATE_NAME.format(language="German", state="Voice missing") == (
        "German voice: Voice missing"
    )
    nodes = [dataclasses.replace(Node("x", "Text"), name="German voice: Piper · Ready")]
    assert voice.state_ready(nodes, strings, "de")
    assert PAUSED == strings.VOICE_MIC_PAUSED
