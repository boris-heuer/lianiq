"""Unit tests of the UIA rows E-03 and E-10 with a faked window and cable (CAP-0174 AC-11).

E-03 passes only when the phrase gives a turn in both panels, the strip shows the running
session in every enabled workspace, Call Bridge Start is disabled with the busy text and F9
from Settings leaves transcript (SHA-256 only), scroll, pair and direction unchanged. E-10
passes only when the export is written without any forbidden pattern and the read-only
folder gives a notice without "Saved" while the event list stays.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from native_e2e.data.make_test_phrase import PHRASE
from native_e2e.evidence.model import Method, Status
from native_e2e.rows import e03, e10
from tests._native_fake_app import ORIGINAL, TRANSLATION, FakeApp, install, make_ctx


@pytest.fixture
def ctx(tmp_path):
    return make_ctx(tmp_path)


def failed(row) -> list[str]:
    return [check.name for check in row.checks if check.result is not Status.PASS]


def run_e03(ctx, monkeypatch, **knobs):
    app = FakeApp(**knobs)
    install(monkeypatch, app)
    return e03.run(ctx), app


# E-03 ---------------------------------------------------------------------------------------


def test_e03_passes_and_stores_the_transcript_as_sha256_only(ctx, monkeypatch) -> None:
    row, app = run_e03(ctx, monkeypatch)
    assert row.status is Status.PASS, row.checks
    assert row.method is Method.VIRTUAL_DEVICE and row.acs == ("AC-11",)
    assert [check.name for check in row.checks] == [
        "test-phrase-sha256",
        "microphone-cable-selected",
        "voice-output-off",
        "session-running",
        "turn-in-original-and-translation",
        "screenshot-running-masked",
        "strip-visible-conversation",
        "strip-visible-meeting",
        "strip-visible-call-bridge",
        "call-bridge-start-disabled-busy",
        "strip-visible-language-packs",
        "strip-visible-settings",
        "stopped-with-f9-from-settings",
        "transcript-sha256-unchanged",
        "scroll-unchanged",
        "pair-unchanged",
        "direction-unchanged",
        "screenshot-after-masked",
    ]
    text = json.dumps(row.to_dict(), ensure_ascii=False)
    assert "Guten Morgen" not in text and "早上好" not in text
    digest = hashlib.sha256(f"{ORIGINAL}\n{TRANSLATION}".encode()).hexdigest()
    assert {c.name: c.detail for c in row.checks}["transcript-sha256-unchanged"] == (
        f"sha256={digest}"
    )
    assert ctx.state["transcripts"] == [ORIGINAL, TRANSLATION]
    assert ORIGINAL in ctx.secrets and TRANSLATION in ctx.secrets  # the scan finds a leak
    assert ctx.state["app"] is app and not app.closed  # E-10 exports from this session
    assert [a.path for a in row.artifacts] == ["screens/e03-running.png", "screens/e03-after.png"]
    assert ctx.state["screens_masked"] == 2


def test_e03_checks_the_phrase_before_any_app_starts(tmp_path, monkeypatch) -> None:
    ctx = make_ctx(tmp_path)
    image = json.loads((ctx.image_root / "image.json").read_text(encoding="utf-8"))
    image["test_phrase"]["sha256"] = "0" * 64
    (ctx.image_root / "image.json").write_text(json.dumps(image), encoding="utf-8")
    row, app = run_e03(ctx, monkeypatch)
    assert failed(row) == ["test-phrase-sha256"]
    assert app.launches == 0


@pytest.mark.parametrize(
    ("knobs", "check"),
    [
        ({"no_turn": True}, "turn-in-original-and-translation"),
        ({"missing": {"Translation"}}, "turn-in-original-and-translation"),
        ({"missing": {"Conversation running", "Active session"}}, "session-running"),
        ({"bridge_start_enabled": True}, "call-bridge-start-disabled-busy"),
        ({"missing": {"Start call bridge"}}, "call-bridge-start-disabled-busy"),
        ({"f9_ignored": True}, "stopped-with-f9-from-settings"),
        ({"changed": True}, "transcript-sha256-unchanged"),
    ],
)
def test_e03_fails_on_a_missing_element_or_changed_state(ctx, monkeypatch, knobs, check) -> None:
    row, _ = run_e03(ctx, monkeypatch, **knobs)
    assert row.status is Status.FAIL
    assert check in failed(row)
    text = json.dumps(row.to_dict(), ensure_ascii=False)
    assert "Guten Morgen" not in text


# E-10 ---------------------------------------------------------------------------------------


def run_e10_after_e03(ctx, monkeypatch, **knobs):
    row, app = run_e03(ctx, monkeypatch, **knobs)
    assert row.status is Status.PASS, row.checks
    return e10.run(ctx), app


def test_e10_exports_after_e03_and_the_protected_file_attempt_fails_visibly(ctx, monkeypatch):
    row, app = run_e10_after_e03(ctx, monkeypatch)
    assert row.status is Status.PASS, row.checks
    assert [check.name for check in row.checks] == [
        "ro-file-denies-write",
        "file-written",
        "no-forbidden-pattern",
        "overwrite-confirmed",
        "failure-notice-shown",
        "notice-without-saved",
        "event-list-kept",
        "screenshot-masked",
    ]
    assert app.launches == 1 and app.closed and "app" not in ctx.state
    assert (ctx.temp / "diagnostics-E10.txt").is_file()
    protected = ctx.temp / "ro" / "diagnostics-E10.txt"
    assert protected in app.readonly
    assert protected.read_text(encoding="utf-8") == e10.PROTECTED_CONTENT  # not replaced
    assert app.prompt is None  # the "replace?" prompt was answered


def test_e10_starts_its_own_app_when_e03_left_none(ctx, monkeypatch) -> None:
    app = FakeApp()
    install(monkeypatch, app)
    row = e10.run(ctx)
    assert row.status is Status.PASS, row.checks
    assert app.launches == 1 and app.closed


@pytest.mark.parametrize(
    ("knobs", "pattern"),
    [
        ({"leak": PHRASE}, "test-phrase, transcript"),  # the phrase is the transcript too
        ({"leak": "Mandarin (Simplified): 早上好，这是一个测试。"}, "transcript"),
        ({"leak": "model at D:\\models"}, "drive-path"),
        ({"leak": "endpoint {0.0.1.00000000}.{x}"}, "endpoint-id"),
        ({"leak": "id windows-mmdevice:v1:capture:{abc-123}"}, "cable-endpoint-id"),
    ],
)
def test_e10_fails_when_the_export_holds_a_forbidden_pattern(ctx, monkeypatch, knobs, pattern):
    row, _ = run_e10_after_e03(ctx, monkeypatch, **knobs)
    checks = {check.name: check for check in row.checks}
    assert checks["no-forbidden-pattern"].result is Status.FAIL
    assert checks["no-forbidden-pattern"].detail == pattern  # classes only, never the match


@pytest.mark.parametrize(
    ("knobs", "check"),
    [
        ({"ro_writable": True}, "failure-notice-shown"),
        ({"no_prompt": True}, "overwrite-confirmed"),
        ({"failure": "Export failed: Saved partially."}, "notice-without-saved"),
    ],
)
def test_e10_fails_without_a_failure_notice_or_with_saved(ctx, monkeypatch, knobs, check) -> None:
    row, app = run_e10_after_e03(ctx, monkeypatch, **knobs)
    assert check in failed(row)
    assert app.closed


def test_e10_fails_when_the_file_is_not_write_protected(ctx, monkeypatch) -> None:
    app = FakeApp()
    install(monkeypatch, app)
    monkeypatch.setattr(e10, "deny_write", lambda path: False)
    row = e10.run(ctx)
    assert failed(row)[0] == "ro-file-denies-write"


# The E-10 forbidden-pattern list (contract §5) ----------------------------------------------

KNOWN = {
    "transcripts": [ORIGINAL, TRANSLATION],
    "phrase": PHRASE,
    "username": "e2e",
    "profile": "C:\\Users\\e2e",
    "endpoint_ids": ["windows-mmdevice:v1:capture:{abc-123}", "{abc-123}"],
}


@pytest.mark.parametrize(
    ("text", "classes"),
    [
        ("12:00 [session] Conversation started\n", []),
        ("native-e2e run and win11-native-e2e@1\n", []),
        ("heard guten morgen, DAS IST EIN TEST.\n", ["test-phrase", "transcript"]),
        ("only DAS IST EIN TEST.\n", []),
        ("早上好，这是一个测试。\n", ["transcript"]),
        ("German: Guten Morgen, das ist ein Test.\n", ["test-phrase", "transcript"]),
        ("user e2e logged\n", ["username"]),
        ("home c:\\users\\E2E\n", ["drive-path", "profile-path", "username"]),
        ("model D:\\x\n", ["drive-path"]),
        ("d:/x stays\n", []),  # contract §5: a drive path is "<letter>:\\"
        ("{0.0.0.00000000}.{x}\n", ["endpoint-id"]),
        ("{0.0.2.00000000}\n", []),
        ("saved id {ABC-123}\n", ["cable-endpoint-id"]),
    ],
)
def test_forbidden_patterns_find_each_class_and_nothing_else(text, classes) -> None:
    assert e10.forbidden_classes(text, **KNOWN) == classes


def test_transcript_needles_are_the_lines_without_the_language_label() -> None:
    needles = e10.transcript_needles([ORIGINAL, "", "x", TRANSLATION])
    assert "Guten Morgen, das ist ein Test." in needles
    assert "早上好，这是一个测试。" in needles
    assert "x" not in needles and "" not in needles
