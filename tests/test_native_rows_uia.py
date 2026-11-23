"""Unit tests of the UIA rows E-01 and E-11 with a faked window and cable (CAP-0174 AC-11).

The real window, pywinauto and VB-Cable exist only in the VM image; ``tests/_native_fake_app``
stands in for them. These tests pin the pass rules of contract §5: E-01 passes only with the
seven entries in order and state (CAP-0177: Meeting second), nothing removed shown in
Conversation and no model file open before Start; E-11 passes only with the migration notice naming the cable (stored as
``name_matches``, never the name) and the migrated keys after the close.
"""

from __future__ import annotations

import json

import pytest

from native_e2e.evidence.model import Method, Status
from native_e2e.rows import e01, e11
from native_e2e.uia import Node
from tests._native_fake_app import (
    CABLE,
    NOTICE_RECT,
    PLANNED,
    SIDEBAR,
    WINDOW,
    FakeApp,
    FakeProcess,
    install,
    make_ctx,
)


@pytest.fixture
def ctx(tmp_path):
    return make_ctx(tmp_path)


def run_e01(ctx, monkeypatch, **knobs):
    app = FakeApp(**knobs)
    install(monkeypatch, app)
    return e01.run(ctx), app


def failed(row) -> list[str]:
    return [check.name for check in row.checks if check.result is not Status.PASS]


# E-01 ---------------------------------------------------------------------------------------


def test_e01_passes_on_the_shell_at_launch_and_closes_the_app(ctx, monkeypatch) -> None:
    row, app = run_e01(ctx, monkeypatch)
    assert row.status is Status.PASS, row.checks
    assert row.method is Method.NATIVE and row.acs == ("AC-11",)
    assert [check.name for check in row.checks] == [
        "sidebar-seven-entries-in-order",
        "conversation-selected",
        "planned-entries-disabled-with-description",
        "call-bridge-experimental",
        "conversation-without-removed-controls",
        "no-model-file-open-before-start",
        "screenshot-masked",
    ]
    assert [artifact.path for artifact in row.artifacts] == ["screens/e01-conversation.png"]
    assert (ctx.out / "screens" / "e01-conversation.png").is_file()
    assert app.closed and "app" not in ctx.state


def _swap(order, a, b):
    order = list(order)
    order[a], order[b] = order[b], order[a]
    return tuple(order)


@pytest.mark.parametrize(
    ("knobs", "check"),
    [
        ({"missing": {"Language packs"}}, "sidebar-seven-entries-in-order"),
        ({"missing": {"Settings"}}, "sidebar-seven-entries-in-order"),
        ({"missing": {"Meeting"}}, "sidebar-seven-entries-in-order"),
        ({"sidebar": _swap(SIDEBAR, 1, 2)}, "sidebar-seven-entries-in-order"),
        (
            {"sidebar": (*SIDEBAR[:3], ("Listen & translate", False, PLANNED), *SIDEBAR[4:])},
            "planned-entries-disabled-with-description",
        ),
        (
            {"sidebar": (*SIDEBAR[:3], ("Listen & translate", False, ""), *SIDEBAR[4:])},
            "planned-entries-disabled-with-description",
        ),
        (
            {"sidebar": (SIDEBAR[0], ("Meeting", False, ""), *SIDEBAR[2:])},
            "planned-entries-disabled-with-description",
        ),
        (
            {"sidebar": (*SIDEBAR[:4], ("Call Bridge", True, ""), *SIDEBAR[5:])},
            "call-bridge-experimental",
        ),
        ({"extra": [Node("Model profile", "ComboBox")]}, "conversation-without-removed-controls"),
        ({"extra": [Node("Start call bridge", "Button")]}, "conversation-without-removed-controls"),
        ({"extra": [Node("Use CUDA GPU", "CheckBox")]}, "conversation-without-removed-controls"),
        (
            {"extra": [Node("Local · Private · Optimized for Ryzen AI 7 350", "Text")]},
            "conversation-without-removed-controls",
        ),
    ],
)
def test_e01_fails_on_a_wrong_or_missing_shell_element(ctx, monkeypatch, knobs, check) -> None:
    row, app = run_e01(ctx, monkeypatch, **knobs)
    assert row.status is Status.FAIL
    assert check in failed(row)
    assert app.closed


def test_e01_fails_when_conversation_is_not_selected(ctx, monkeypatch) -> None:
    app = FakeApp()
    install(monkeypatch, app)
    start = app.start
    monkeypatch.setattr(
        e01.uia_app, "launch", lambda c: setattr(start(c), "page", "Settings") or app
    )
    row = e01.run(ctx)
    assert "conversation-selected" in failed(row)


def test_e01_ignores_controls_of_hidden_pages_and_sidebar_names(ctx, monkeypatch) -> None:
    hidden = Node("Model profile", "ComboBox", visible=False)
    row, _ = run_e01(ctx, monkeypatch, extra=[hidden])
    assert row.status is Status.PASS, row.checks


@pytest.mark.parametrize("where", ["files", "maps"])
@pytest.mark.parametrize("folder", ["repo", "image"])
def test_e01_fails_when_a_model_file_is_open_before_start(ctx, monkeypatch, where, folder) -> None:
    base = ctx.repo / "models" if folder == "repo" else ctx.image()["models_dir"]
    path = str(base).upper() + "\\faster-whisper-small\\model.bin"  # Windows: any case
    row, _ = run_e01(ctx, monkeypatch, process={where: [path]})
    assert failed(row) == ["no-model-file-open-before-start"]
    assert path not in json.dumps(row.to_dict())  # the count only, never the path


def test_e01_passes_with_files_open_outside_the_models_folder(ctx, monkeypatch) -> None:
    outside = [str(ctx.repo / "lianiq" / "app.py"), str(ctx.repo / "models-old" / "x.bin")]
    row, _ = run_e01(ctx, monkeypatch, process={"files": outside, "maps": outside})
    assert row.status is Status.PASS, row.checks


def test_models_in_use_checks_every_app_process() -> None:
    roots = ["C:\\e2e\\models"]
    clean, busy = FakeProcess(), FakeProcess(maps=["c:\\E2E\\Models\\x.onnx"])
    assert e01.models_in_use([clean], roots) == 0
    assert e01.models_in_use([clean, busy], roots) == 1


# E-11 ---------------------------------------------------------------------------------------


def run_e11(ctx, monkeypatch, **knobs):
    app = FakeApp(**knobs)
    install(monkeypatch, app)
    seen = {}
    start = app.start

    def launch(c):
        seen["settings"] = json.loads(c.local_settings.read_text(encoding="utf-8"))
        return start(c)

    monkeypatch.setattr(e11.uia_app, "launch", launch)
    return e11.run(ctx), app, seen


def test_e11_writes_legacy_settings_reads_the_notice_and_the_migrated_keys(
    ctx, monkeypatch
) -> None:
    row, app, seen = run_e11(ctx, monkeypatch)
    assert row.status is Status.PASS, row.checks
    assert row.method is Method.VIRTUAL_DEVICE
    audio = seen["settings"]["audio"]
    assert audio["input_device"] == 7
    assert not [key for key in audio if key.endswith(("_policy", "_endpoint_id", "_device_name"))]
    assert seen["settings"]["schema_version"] == 2
    assert [check.name for check in row.checks] == [
        "legacy-settings-written",
        "migration-notice-shown",
        "name_matches",
        "screenshot-masked",
        "input-device-null",
        "policy-keys-set",
    ]
    names = {check.name: check for check in row.checks}
    assert names["name_matches"].detail == "name_matches: true"
    assert CABLE.casefold() not in json.dumps(row.to_dict(), ensure_ascii=False).casefold()
    assert app.closed


def test_the_template_is_a_legacy_device_choice_without_identity_keys() -> None:
    data = json.loads(e11.TEMPLATE.read_text(encoding="utf-8"))
    assert data == {"schema_version": 2, "audio": {"input_device": None}}
    assert json.loads(e11.legacy_settings(3))["audio"] == {"input_device": 3}


@pytest.mark.parametrize(
    ("knobs", "check"),
    [
        ({"migrated_name": "Microphone (Realtek Audio)"}, "name_matches"),
        ({"no_notice": True}, "migration-notice-shown"),
        ({"keep_index": True}, "input-device-null"),
    ],
)
def test_e11_fails_on_a_wrong_name_no_notice_or_unmigrated_keys(
    ctx, monkeypatch, knobs, check
) -> None:
    row, app, _ = run_e11(ctx, monkeypatch, **knobs)
    assert row.status is Status.FAIL
    assert check in failed(row)
    assert app.closed
    assert "realtek" not in json.dumps(row.to_dict()).casefold()


def test_e11_screenshot_masks_the_notice_before_it_is_written(ctx, monkeypatch) -> None:
    from PySide6.QtGui import QImage

    run_e11(ctx, monkeypatch)
    assert ctx.state["screens_masked"] == 1
    image = QImage(str(ctx.out / "screens" / "e11-migration-notice.png"))
    left, top, right, bottom = NOTICE_RECT
    for x in range(left, right, 7):
        for y in range(top, bottom, 5):
            assert image.pixelColor(x - WINDOW[0], y - WINDOW[1]).rgb() == 0xFF000000, (x, y)
    assert image.pixelColor(5, 400).red() == 255  # outside the masked rectangles
