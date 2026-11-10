"""AC-35 evidence mode of ``scripts/capture_readme_screenshot.py`` (CAP-0168 WI-06, spec §9 T1).

``--evidence <folder>`` writes one PNG per enabled workspace and AC-29 size into that local
folder and prints ``<sha256>  <file>`` per screenshot. Nothing is written elsewhere, and no
transcript text, endpoint ID or absolute path reaches a file name or the output.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.ui.shell.workspaces import DEFAULT_ENTRIES, WorkspaceId

AC29_SIZES = ((850, 560), (1120, 720), (1280, 720), (1440, 900))
ENABLED = (WorkspaceId.CONVERSATION, WorkspaceId.CALL_BRIDGE, WorkspaceId.SETTINGS)
LINE = re.compile(r"^(?P<digest>[0-9a-f]{64})  (?P<name>[^\s/\\]+\.png)$")


def load_capture_module():
    script = Path(__file__).parents[2] / "scripts" / "capture_readme_screenshot.py"
    spec = importlib.util.spec_from_file_location("capture_readme_screenshot", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def evidence_run(tmp_path, monkeypatch, capsys):
    """One evidence run into ``tmp_path / "evidence"``; every grab is recorded."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    import lianiq.ui.main_window as main_window_module

    QApplication.instance() or QApplication([])
    capture = load_capture_module()
    grabs = []
    original_grab = main_window_module.MainWindow.grab

    def record_grab(window, *args):
        held = window.held_turn_bar.isVisible()  # read while the screenshot is taken
        grabs.append((window.current_workspace(), window.width(), window.height(), window, held))
        return original_grab(window, *args)

    monkeypatch.setattr(main_window_module.MainWindow, "grab", record_grab)
    readme_asset = capture.DEFAULT_OUTPUT.read_bytes()
    folder = tmp_path / "evidence"
    code = capture.main(["--evidence", str(folder)])
    out, err = capsys.readouterr()
    return capture, code, folder, out, err, grabs, readme_asset


def test_the_enabled_workspaces_are_the_selectable_registry_entries() -> None:
    capture = load_capture_module()
    assert capture.EVIDENCE_SIZES == AC29_SIZES
    assert capture.evidence_workspaces() == ENABLED
    assert ENABLED == tuple(item.id for item in DEFAULT_ENTRIES if item.selectable)


def test_evidence_mode_writes_one_png_per_enabled_workspace_and_size(evidence_run) -> None:
    capture, code, folder, _out, _err, grabs, _asset = evidence_run

    assert code == 0
    files = sorted(path.name for path in folder.iterdir())
    assert len(files) == len(ENABLED) * len(AC29_SIZES) == 12
    assert files == sorted(
        capture.evidence_name(workspace, width, height, grabs[0][3].devicePixelRatioF())
        for workspace in ENABLED
        for width, height in AC29_SIZES
    )
    assert all(name.endswith(".png") and (folder / name).stat().st_size > 0 for name in files)
    # Each screenshot shows its workspace at its size; below 1000 px the sidebar is the rail.
    shown = [(workspace, width, height) for workspace, width, height, _window, _held in grabs]
    assert shown == [(w, *size) for w in ENABLED for size in AC29_SIZES]


def test_each_screenshot_has_the_window_size_in_device_pixels(evidence_run) -> None:
    from PySide6.QtGui import QImage

    capture, _code, folder, _out, _err, grabs, _asset = evidence_run
    ratio = grabs[0][3].devicePixelRatioF()
    for workspace in ENABLED:
        for width, height in AC29_SIZES:
            image = QImage(str(folder / capture.evidence_name(workspace, width, height, ratio)))
            assert (image.width(), image.height()) == (round(width * ratio), round(height * ratio))


def test_printed_sha256_lines_match_the_written_files(evidence_run) -> None:
    _capture, _code, folder, out, _err, _grabs, _asset = evidence_run

    lines = out.strip().splitlines()
    assert len(lines) == 12
    printed = {}
    for line in lines:
        match = LINE.match(line)
        assert match, line
        printed[match["name"]] = match["digest"]
    assert set(printed) == {path.name for path in folder.iterdir()}
    for name, digest in printed.items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest


def test_evidence_mode_writes_nothing_outside_the_folder(evidence_run, tmp_path) -> None:
    capture, _code, folder, _out, _err, _grabs, readme_asset = evidence_run

    assert [path.name for path in tmp_path.iterdir()] == ["evidence"]
    assert all(path.is_file() and path.parent == folder for path in folder.iterdir())
    assert capture.DEFAULT_OUTPUT.read_bytes() == readme_asset  # the README image is untouched


def test_no_transcript_text_endpoint_id_or_path_in_names_or_output(evidence_run) -> None:
    capture, _code, folder, out, err, grabs, _asset = evidence_run

    names = " ".join(path.name for path in folder.iterdir())
    forbidden = [
        capture.SAMPLE_HELD_TURN.transcript.text,
        "audio-endpoint:",
        "windows-mmdevice:",
        *(device.endpoint_id for device in capture.GENERIC_DEVICES),
        *(device.display_name for device in capture.GENERIC_DEVICES),
        str(folder),
        str(Path.home()),
    ]
    for text in (names, out, err):
        for item in forbidden:
            assert item not in text, item
    # The evidence window shows no held turn, so no transcript text is rendered either.
    assert len(grabs) == 12
    assert [held for *_rest, held in grabs] == [False] * 12


def test_evidence_mode_restores_the_patches(evidence_run) -> None:
    import lianiq.ui.device_setup as device_setup_module
    import lianiq.ui.workspaces.call_bridge as call_bridge_module
    from lianiq.audio import device_inventory, endpoints

    _capture, code, *_rest = evidence_run
    assert code == 0
    assert device_setup_module.read_inventory is device_inventory.read_inventory
    assert call_bridge_module.list_audio_endpoints is endpoints.list_audio_endpoints


def test_the_rail_is_shown_below_1000_px(tmp_path, monkeypatch) -> None:
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    import lianiq.ui.main_window as main_window_module

    QApplication.instance() or QApplication([])
    capture = load_capture_module()
    compact = []
    original_grab = main_window_module.MainWindow.grab

    def record_grab(window, *args):
        compact.append((window.width(), window.navigation.compact))
        return original_grab(window, *args)

    monkeypatch.setattr(main_window_module.MainWindow, "grab", record_grab)
    assert capture.main(["--evidence", str(tmp_path / "rail")]) == 0
    assert compact and all(rail == (width < 1000) for width, rail in compact)
