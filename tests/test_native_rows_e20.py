"""Unit tests of the Text translation rows E-20..E-23 with a faked window (CAP-0172 ACs).

``FakeText`` (``tests/_native_fake_text.py``) stands in for the window, the assistant, the
pack dialogs, the cable and the clipboard. The tests pin the pass path of each row, that
results are stored as SHA-256 only with both panes masked, that the scratch group restores
the settings, and the blocked and failing cases.
"""

from __future__ import annotations

import json

import pytest

from native_e2e.evidence.model import Method, Status
from native_e2e.rows import e20, e23, text_flow
from tests._native_fake_app import make_ctx
from tests._native_fake_text import FakeText, install

ALL_PACKS = ("mt-de-zh-hans", "mt-zh-hans-de", "tts-de-thorsten-medium", "tts-zh-hans-aishell3")


@pytest.fixture
def ctx(tmp_path):
    return make_ctx(tmp_path)


def group(ctx, monkeypatch, tmp_path, **knobs):
    app = FakeText(**knobs)
    seen = install(monkeypatch, app, tmp_path)
    rows = [e20.run(ctx), e20.run_e21(ctx), e20.run_e22(ctx)]
    return rows, app, seen


def test_the_scratch_group_passes_and_stores_texts_as_sha256_only(
    ctx, monkeypatch, tmp_path
) -> None:
    rows, app, seen = group(ctx, monkeypatch, tmp_path)
    assert [row.id for row in rows] == ["E-20", "E-21", "E-22"]
    assert all(row.status is Status.PASS for row in rows), [r.checks for r in rows]
    assert [row.method for row in rows] == [Method.NATIVE, Method.NATIVE, Method.VIRTUAL_DEVICE]
    assert rows[0].acs == ("AC-31", "AC-32") and rows[1].acs == ("AC-07", "AC-28")
    assert app.closed and app.launches == 1 and seen == {"resets": 1, "scratch": ["e20"]}
    names = [check.name for check in rows[2].checks]
    assert names[-5:] == [
        "stopped-reads-replay",
        "replay-played",
        "stale-at-once-controls-disabled",
        "screenshot-stale-masked",
        "target-changed-still-disabled",
    ]
    stored = json.dumps([row.to_dict() for row in rows], ensure_ascii=False)
    assert "Guten" not in stored and "早上好" not in stored and "CABLE" not in stored
    assert "译文" not in stored
    assert {*text_flow.D03.split("\n\n"), text_flow.D04} <= set(ctx.secrets)
    paths = [a.path for row in rows for a in row.artifacts]
    assert len(paths) == 6 and all((ctx.out / path).is_file() for path in paths)


def test_the_group_is_blocked_without_the_pack_file(ctx, monkeypatch, tmp_path) -> None:
    app = FakeText()
    seen = install(monkeypatch, app, tmp_path)
    seen["no_pack_file"] = True
    rows = [e20.run(ctx), e20.run_e21(ctx), e20.run_e22(ctx)]
    assert {row.status for row in rows} == {Status.BLOCKED}
    assert {row.reason for row in rows} == {"image-packs-without-pack-file"}
    assert app.launches == 0 and seen["scratch"] == []


def test_e21_and_e22_are_blocked_when_e20_imports_nothing(ctx, monkeypatch, tmp_path) -> None:
    rows, app, seen = group(ctx, monkeypatch, tmp_path, no_get=True)
    assert rows[0].status is Status.FAIL
    assert [c.detail for c in rows[0].checks if c.result is Status.FAIL] == ["get-not-shown"]
    assert [row.reason for row in rows[1:]] == ["translation-packs-not-ready"] * 2
    assert app.closed and seen["resets"] == 1


def test_e22_fails_when_an_edit_does_not_mark_the_result_stale(ctx, monkeypatch, tmp_path) -> None:
    rows, _app, _seen = group(ctx, monkeypatch, tmp_path, no_stale=True)
    failed = [c.name for c in rows[2].checks if c.result is Status.FAIL]
    assert rows[2].status is Status.FAIL and failed == ["stale-at-once-controls-disabled"]


def test_e23_passes_with_session_rule_limit_and_no_sentinel_left(
    ctx, monkeypatch, tmp_path
) -> None:
    app = FakeText(packs=ALL_PACKS)
    seen = install(monkeypatch, app, tmp_path)
    (ctx.repo / "logs").mkdir()
    (ctx.repo / "logs" / "lianiq.log").write_text("no text here\n", encoding="utf-8")
    row = e23.run(ctx)
    assert row.status is Status.PASS, row.checks
    assert row.acs == ("AC-12", "AC-21", "AC-26", "AC-27", "AC-33")
    assert app.launches == 2 and app.closed and seen["resets"] == 1
    sentinel = next(c for c in row.checks if c.name == "sentinel-in-no-file")
    assert sentinel.detail == "files=2 hits=0"
    assert text_flow.SENTINEL in ctx.secrets
    assert "QX7" not in json.dumps(row.to_dict())


def test_e23_fails_when_a_log_holds_the_sentinel(ctx, monkeypatch, tmp_path) -> None:
    install(monkeypatch, FakeText(packs=ALL_PACKS), tmp_path)
    (ctx.repo / "logs").mkdir()
    (ctx.repo / "logs" / "lianiq.log").write_text(f"{text_flow.SENTINEL}\n", encoding="utf-8")
    row = e23.run(ctx)
    failed = [c for c in row.checks if c.result is Status.FAIL]
    assert [c.name for c in failed] == ["sentinel-in-no-file"] and failed[0].detail.endswith("1")


def test_d06_is_one_code_point_over_the_limit() -> None:
    text = text_flow.over_limit()
    assert len(text) == text_flow.limit() + 1 == 5001 and text == "Ab. " * 1250 + "x"
