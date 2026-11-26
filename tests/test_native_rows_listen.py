"""Unit tests of the Listen & translate rows E-24..E-26 (CAP-0170; spec §2.2).

The rows drive ``tests._native_listen_app.ListenFlowApp``; a pass test per row and one test
per row that shows a pass rule can fail. The evidence holds counts and SHA-256 only.
"""

from __future__ import annotations

import json

from native_e2e import packs_import
from native_e2e.evidence.model import Method, Status
from native_e2e.rows import e24, e25, e26
from native_e2e.rows import listen_flow as lf
from tests._native_listen_app import REVIEW, ListenFlowApp, install_listen


def failed(row) -> list[str]:
    return [check.name for check in row.checks if check.result is not Status.PASS]


def group(tmp_path, monkeypatch, **knobs):
    app = ListenFlowApp(**knobs)
    ctx = install_listen(monkeypatch, tmp_path, app)
    first = e24.run(ctx)
    return ctx, app, first, e25.run(ctx)


def test_listen_packs_are_the_german_mandarin_pair_only() -> None:
    assert lf.packs() == {
        "recognition": "stt-faster-whisper-small",
        "de>zh-Hans": "mt-de-zh-hans",
        "zh-Hans>de": "mt-zh-hans-de",
    }


def test_e24_and_e25_pass_on_the_scratch_models_and_store_no_text(tmp_path, monkeypatch) -> None:
    ctx, app, e24_row, e25_row = group(tmp_path, monkeypatch)
    assert e24_row.status is Status.PASS, e24_row.checks
    assert e25_row.status is Status.PASS, e25_row.checks
    assert e24_row.acs == ("AC-25",) and e25_row.method is Method.VIRTUAL_DEVICE
    details = {c.name: c.detail for c in e25_row.checks}
    assert details["three-rows-in-order"] == "rows=3"
    assert details["transcript-v2-turns"] == "de-zh=3 zh-de=2"
    assert app.installed == set(REVIEW) and app.closed and not ctx.local_settings.exists()
    text = json.dumps([e24_row.to_dict(), e25_row.to_dict()], ensure_ascii=False)
    assert "Guten Morgen" not in text and "Fracht" not in text and "早上好" not in text
    assert "Der Preis enthält die Fracht." in ctx.secrets


def test_e24_fails_with_a_voice_row_in_the_readiness(tmp_path, monkeypatch) -> None:
    _ctx, _app, e24_row, _e25_row = group(tmp_path, monkeypatch, voice_row=True)
    assert failed(e24_row) == ["readiness-no-voice-no-speakers"]


def test_e25_fails_when_the_german_sentence_gets_a_mandarin_target(tmp_path, monkeypatch) -> None:
    _ctx, _app, _e24_row, e25_row = group(tmp_path, monkeypatch, wrong_target=True)
    assert "mandarin-rows-to-german" in failed(e25_row)


def test_e24_and_e25_are_blocked_without_pack_files(tmp_path, monkeypatch) -> None:
    app = ListenFlowApp()
    ctx = install_listen(monkeypatch, tmp_path, app)
    monkeypatch.setattr(packs_import, "has_pack_file", lambda folder: False)
    assert e24.run(ctx).reason == e25.run(ctx).reason == "image-packs-without-pack-file"
    assert app.launches == 0


def run_e26(tmp_path, monkeypatch, **knobs):
    app = ListenFlowApp(installed=("stt-faster-whisper-small", "mt-de-zh-hans"), **knobs)
    ctx = install_listen(monkeypatch, tmp_path, app)
    ctx.temp.mkdir(parents=True)
    return e26.run(ctx), app, ctx


def test_e26_passes_and_stores_counts_only(tmp_path, monkeypatch) -> None:
    row, app, ctx = run_e26(tmp_path, monkeypatch)
    assert row.status is Status.PASS, row.checks
    assert row.acs == ("AC-10", "AC-12", "AC-13", "AC-19", "AC-21", "AC-27", "AC-32")
    details = {c.name: c.detail for c in row.checks}
    assert details["stopping-at-once"] == "first=stopping" and app.launches == 2
    assert "QX7" not in json.dumps(row.to_dict(), ensure_ascii=False)
    assert "Lianiq Kontrollsatz QX7 Hörprobe." in ctx.secrets


def test_e26_fails_when_the_sentinel_reaches_the_log(tmp_path, monkeypatch) -> None:
    row, _app, _ctx = run_e26(tmp_path, monkeypatch, leak=True)
    assert failed(row) == ["no-sentinel-or-row-text"]


def test_e26_counts_a_new_wav_file(tmp_path) -> None:
    (tmp_path / "a" / "models").mkdir(parents=True)
    (tmp_path / "a" / "models" / "old.wav").write_bytes(b"x")  # skipped folder
    (tmp_path / "a" / "new.wav").write_bytes(b"x")
    assert e26.new_wavs([tmp_path / "a"], 0) == 1


def test_e26_fails_a_stop_that_takes_41_seconds_from_f9(tmp_path, monkeypatch) -> None:
    times = iter((0.0, 1.0))
    monkeypatch.setattr(e26, "clock", lambda: next(times, 41.0))
    row, _app, _ctx = run_e26(tmp_path, monkeypatch)
    assert failed(row) == ["stopped-within-40s"]
    assert {c.name: c.detail for c in row.checks}["stopped-within-40s"] == "seconds=41.0"


def test_e26_remembers_the_rows_of_the_stopped_session(tmp_path, monkeypatch) -> None:
    _row, _app, ctx = run_e26(tmp_path, monkeypatch)
    assert "Wir liefern die Ware nächste Woche." in ctx.secrets


def test_a_raising_e24_group_still_closes_the_app_and_resets(tmp_path, monkeypatch) -> None:
    from native_e2e import uia_app

    app = ListenFlowApp()
    ctx = install_listen(monkeypatch, tmp_path, app)
    resets = []
    monkeypatch.setattr(uia_app, "settings_reset", lambda c: resets.append(c) or True)

    def boom(*args):
        raise RuntimeError("x")

    monkeypatch.setattr(e24, "_guarded", boom)
    assert e24.run(ctx).reason == e25.run(ctx).reason == "unexpected-error"
    assert app.closed and resets == [ctx]
