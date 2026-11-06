"""``scripts/capture_readme_screenshot.py`` builds a ready window without models (WI-07)."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def load_capture_module():
    script = Path(__file__).parents[2] / "scripts" / "capture_readme_screenshot.py"
    spec = importlib.util.spec_from_file_location("capture_readme_screenshot", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_screenshot_window_is_ready_with_the_default_pair_and_generic_devices(tmp_path) -> None:
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    import lianiq.ui.main_window as main_window_module

    QApplication.instance() or QApplication([])
    capture = load_capture_module()
    original_devices = main_window_module.list_audio_devices
    output = tmp_path / "application-ui.png"

    assert capture.main(["--output", str(output)]) == 0

    assert output.stat().st_size > 0
    assert main_window_module.list_audio_devices is original_devices  # patches are restored


def test_screenshot_pipeline_reports_the_default_pair_ready_without_loading_models(
    monkeypatch,
) -> None:
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    import lianiq.ui.main_window as main_window_module
    from lianiq.config import AppConfig

    QApplication.instance() or QApplication([])
    capture = load_capture_module()
    monkeypatch.setattr(
        main_window_module, "list_audio_devices", lambda: list(capture.GENERIC_DEVICES)
    )
    config = AppConfig()
    pipeline = capture.build_screenshot_pipeline(config)

    window = main_window_module.MainWindow(config, pipeline, persist_settings=False)
    try:
        assert window.pair_combo.currentText() == "German ↔ Mandarin (Simplified)"
        assert window.start_button.isEnabled()
        inputs = [window.input_combo.itemText(i) for i in range(window.input_combo.count())]
        assert "Microphone" in inputs
    finally:
        window.close()
    assert pipeline.recognizer is not None and pipeline.synthesizer is None


def test_screenshot_shows_the_sample_held_turn_with_one_button_per_pair_member(
    tmp_path, monkeypatch
) -> None:
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    import lianiq.ui.main_window as main_window_module

    QApplication.instance() or QApplication([])
    capture = load_capture_module()
    shown = []
    original_close = main_window_module.MainWindow.close

    def record_and_close(window):
        bar = window.held_turn_bar
        shown.append((bar.isVisible(), bar.turn, sorted(bar.translate_buttons)))
        return original_close(window)

    monkeypatch.setattr(main_window_module.MainWindow, "close", record_and_close)

    assert capture.main(["--output", str(tmp_path / "application-ui.png")]) == 0

    assert shown == [(True, capture.SAMPLE_HELD_TURN, ["de", "zh-Hans"])]
