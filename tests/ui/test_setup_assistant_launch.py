"""CAP-0171 WI-06: who opens the setup assistant (C §9; offscreen, socket guard).

``lianiq.app.main`` opens it on a first launch only: not with ``--no-setup-assistant``, not
after an upgrade (the upgrade half of AC-31) and never from a directly built ``MainWindow``
(AC-32). The window runs over the fake devices and spy adapters of ``_spy_window``.
"""

from __future__ import annotations

import json

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

import lianiq.config as config_module
import lianiq.ui.main_window as main_window_module
from lianiq import app
from lianiq.languages import ReadinessProbe
from tests._spy_window import build_window, spies  # noqa: F401
from tests.packs.conftest import network_attempts  # noqa: F401
from tests.ui._language_packs_helpers import packs_network  # noqa: F401 - the fixture


def test_ac32_a_directly_built_window_opens_no_assistant(tmp_path, spies, monkeypatch) -> None:  # noqa: F811
    window = build_window(tmp_path, monkeypatch)
    try:
        QApplication.processEvents()
        assert getattr(window, "setup_assistant", None) is None
        assert window.current_workspace().value == "conversation"
    finally:
        window.close()


def run_main(tmp_path, monkeypatch, argv, local_settings: str | None):
    """``lianiq.app.main`` over the fake devices and spy adapters; returns what showed."""
    default = tmp_path / "settings.json"
    default.write_text(config_module.DEFAULT_CONFIG_PATH.read_text("utf-8"), "utf-8")
    local = tmp_path / "settings.local.json"
    if local_settings is not None:
        local.write_text(local_settings, "utf-8")
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", default)
    monkeypatch.setattr(config_module, "LOCAL_CONFIG_PATH", local)
    monkeypatch.setattr(app, "LOCAL_CONFIG_PATH", local)
    build_window(tmp_path / "fakes", monkeypatch).close()  # installs the fake devices
    monkeypatch.setattr(app, "configure_logging", lambda *_args: None)
    monkeypatch.setattr(app, "recover_packs", lambda: None)
    real_build = app.build_pipeline
    monkeypatch.setattr(
        app, "build_pipeline", lambda config: real_build(config, probe=ReadinessProbe(tmp_path))
    )
    windows, seen = [], {}
    real_window = main_window_module.MainWindow

    def window_factory(*args, **kwargs):
        windows.append(real_window(*args, **kwargs))
        return windows[-1]

    def inspect() -> None:
        assistant = getattr(windows[0], "setup_assistant", None)
        seen["assistant"] = assistant is not None and assistant.isVisible()
        seen["first_run"] = windows[0].config.provisioning.first_run
        if assistant is not None:
            assistant.close()  # the close button equals Skip
        windows[0].close()
        QApplication.quit()

    monkeypatch.setattr(main_window_module, "MainWindow", window_factory)
    QTimer.singleShot(0, inspect)
    assert app.main(argv) == 0
    return seen, (json.loads(local.read_text("utf-8")) if local.exists() else None)


def test_ac01_first_launch_opens_the_assistant(tmp_path, spies, monkeypatch, network) -> None:  # noqa: F811
    seen, saved = run_main(tmp_path, monkeypatch, [], None)
    assert seen == {"assistant": True, "first_run": "pending"}
    assert saved["provisioning"]["first_run"] == "skipped"
    assert network == []


def test_ac32_no_setup_assistant_flag(tmp_path, spies, monkeypatch) -> None:  # noqa: F811
    seen, _ = run_main(tmp_path, monkeypatch, [app.NO_SETUP_ASSISTANT], None)
    assert seen == {"assistant": False, "first_run": "pending"}


def test_ac31_upgrade_opens_no_assistant_and_saves_completed(tmp_path, spies, monkeypatch) -> None:  # noqa: F811
    seen, saved = run_main(tmp_path, monkeypatch, [], '{"schema_version": 2}')
    assert seen == {"assistant": False, "first_run": "completed"}
    assert saved["provisioning"]["first_run"] == "completed"


def test_a_provisioning_section_that_is_not_an_object_shows_the_settings_error(
    tmp_path, monkeypatch
) -> None:
    local = tmp_path / "settings.local.json"
    local.write_text('{"schema_version": 2, "provisioning": null}', "utf-8")
    monkeypatch.setattr(config_module, "LOCAL_CONFIG_PATH", local)
    monkeypatch.setattr(app, "LOCAL_CONFIG_PATH", local)
    reported = []
    monkeypatch.setattr(app, "report_settings_error", reported.append)
    assert app.main([]) == 2
    assert "provisioning must be an object" in str(reported[0])
