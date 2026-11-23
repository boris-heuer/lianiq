"""Requirement-scoped warm-up through the MainWindow (CAP-0169 AC-20).

Split from ``test_requirement_scoped_loading.py``; the spy adapters and the window builder
are in ``tests/_spy_window.py``.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.languages import OutputKind
from tests._spy_window import build_window
from tests._spy_window import spies as spy_adapters_fixture  # noqa: F401


class TestMainWindowLoadsOnlyOnStart:
    """AC-20: no model loads before Start; Start loads only mode-required adapters."""

    @pytest.fixture
    def window(self, tmp_path, spies, monkeypatch):
        window = build_window(tmp_path, monkeypatch)
        yield window
        window.close()

    @staticmethod
    def wait_until(condition, timeout_ms: int = 3_000) -> bool:
        from PySide6.QtTest import QTest

        waited = 0
        while not condition() and waited < timeout_ms:
            QTest.qWait(10)
            waited += 10
        return condition()

    @staticmethod
    def set_voices(window, on: bool) -> None:
        """Turn every enabled voice switch on or off (CAP-0167 voice rows)."""
        rows = window.voice_rows
        for language in rows.languages():
            switch = rows.switch(language)
            if switch.isEnabled() and switch.isChecked() is not on:
                switch.click()

    @pytest.mark.parametrize(
        ("mode_label", "spoken", "recognition", "edges", "voices"),
        [
            (
                "Automatic (German ↔ Mandarin (Simplified))",
                False,
                ["de", "zh-Hans"],
                ["de>zh-Hans", "zh-Hans>de"],
                None,
            ),
            ("German → Mandarin (Simplified)", False, ["de"], ["de>zh-Hans"], None),
            ("Mandarin (Simplified) → German", True, ["zh-Hans"], ["zh-Hans>de"], ["de"]),
        ],
    )
    def test_ac20_start_warms_only_the_started_modes_requirements(
        self, window, spies, mode_label, spoken, recognition, edges, voices
    ) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        QTest.qWait(50)
        assert spies.constructed == []  # nothing constructed or loaded before Start
        assert window.start_button.isEnabled()

        window.mode_combo.setCurrentText(mode_label)
        self.set_voices(window, spoken)
        assert spies.constructed == []
        QTest.mouseClick(window.start_button, Qt.MouseButton.LeftButton)

        assert self.wait_until(lambda: window.capture.running)
        assert spies.recognizer.warmed_languages == recognition
        assert spies.translator.warmed_edges == edges
        if voices is None:
            assert spies.synthesizer is None
            assert spies.constructed == ["recognizer", "translator"]
        else:
            assert spies.synthesizer.warmed_languages == voices
        window.stop_listening()

    @pytest.mark.parametrize("spoken", [False, True])
    def test_voice_output_is_bound_at_start_and_locked_while_models_load(
        self, window, spies, spoken
    ) -> None:
        # CAP-0169 AC-13 (WI-04 review F6): the voice switches are part of the session bound
        # at Start; they are disabled while the models load and while the session runs.
        window.mode_combo.setCurrentText("German → Mandarin (Simplified)")
        self.set_voices(window, spoken)
        switch = window.voice_rows.switch(window.voice_rows.languages()[1])  # the target
        spies.release_warm_up.clear()
        window.start_listening()
        assert not switch.isEnabled()
        assert switch.toolTip() == "Stop the session to change language pair or mode"
        switch.setChecked(not spoken)  # a programmatic toggle changes nothing
        spies.release_warm_up.set()

        assert self.wait_until(lambda: window.capture.running)
        assert window.pipeline.voice_output is spoken
        expected = OutputKind.SPOKEN if spoken else OutputKind.TEXT
        assert window.session_controller.session.mode.output is expected
        assert not switch.isEnabled() and switch.isChecked() is spoken
        window.stop_listening()
        assert switch.isEnabled()

    def test_a_stopped_start_never_starts_capture_for_the_next_start(self, window, spies) -> None:
        spies.failing_warm_up_calls = {2}
        spies.release_warm_up.clear()
        window.start_listening()  # Start A; its warm-up blocks
        assert self.wait_until(lambda: spies.translator is not None)
        window.stop_listening()
        window.mode_combo.setCurrentText("German → Mandarin (Simplified)")
        window.start_listening()  # Start B; its warm-up fails
        spies.release_warm_up.set()

        assert self.wait_until(lambda: window.state_label.text() == "Model error")
        # CAP-0168 WI-03: the failure is a blocking notice, no longer status-bar text.
        from lianiq.ui.shell.workspaces import WorkspaceId

        notice = window.notices.top(WorkspaceId.CONVERSATION)
        assert notice.title == "Models could not be prepared: warm-up 2 failed"
        assert not window.capture.running
        assert window.start_button.isEnabled()
