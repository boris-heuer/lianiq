"""AC-29 (UI): the size × scale × work-area matrix (CAP-0168 WI-05; spec §2.3.7, E-08).

For each ``QT_SCALE_FACTOR`` 1, 1.25, 1.5 and 2 a subprocess (``_layout_probe``; Qt reads
the factor once at start) shows every enabled workspace at 850×560, 1120×720, 1280×720 and
1440×900, stopped and running, and then in an 800×500 work area. Start and Stop are in view
and outside the scroll areas, no button or label text is cut (scrolling allowed), and below
1000 px the sidebar is the icon rail with unchanged accessible names. Offscreen code
evidence; native scaling and text scaling are WI-06 (AC-30).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.ui.shell.workspaces import WorkspaceId
from tests._spy_window import build_window, spies  # noqa: F401
from tests.ui._layout_checks import elided, in_view, load_ui_fonts, settle
from tests.ui._layout_probe import SIZES, WORK_AREA

ROOT = Path(__file__).resolve().parents[2]
SCALES = ("1", "1.25", "1.5", "2")


@pytest.fixture
def window(tmp_path, spies, monkeypatch):  # noqa: F811
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    load_ui_fonts()
    window = build_window(tmp_path, monkeypatch)
    yield window
    window.stop_listening()
    window.close()


@pytest.mark.parametrize("scale", SCALES)
def test_ac29_matrix_at_each_scale_factor(scale) -> None:
    pytest.importorskip("PySide6")
    path = os.pathsep.join(filter(None, (str(ROOT), os.environ.get("PYTHONPATH"))))
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_SCALE_FACTOR": scale}
    env["PYTHONPATH"] = path
    result = subprocess.run(
        [sys.executable, "-m", "tests.ui._layout_probe"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["ratio"] == float(scale)  # the factor really applied
    assert report["problems"] == []
    assert len(SIZES) == 4 and WORK_AREA == (800, 500)


def test_e08_text_scaling_150_percent_at_1120_by_720(tmp_path, spies, monkeypatch) -> None:  # noqa: F811
    """Windows text scaling 150 % (a 13.5 pt system font): the rows wrap, nothing is cut."""
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from lianiq.ui import theme
    from tests.ui._layout_checks import matrix_problems

    application = QApplication.instance() or QApplication([])
    load_ui_fonts()
    system = QFont(application.font())
    larger = QFont(system)
    larger.setPointSizeF(system.pointSizeF() * 1.5)
    application.setFont(larger)
    window = build_window(tmp_path, monkeypatch)
    try:
        theme.apply(window, high_contrast=False)
        assert "font-size: 16.88pt" in window.styleSheet()
        assert matrix_problems(window, 1120, 720) == []
        conversation = window.conversation
        assert conversation._action_row.wrapped  # Voice output and Export moved down
        assert conversation._field_row.stacked  # Conversation direction under Language pair
        settle(window, 1900, 900)  # wide again: one line, in the original order
        assert not conversation._action_row.wrapped and not conversation._field_row.stacked
        row = [window.start_button, window.swap_button, window.tts_checkbox]
        row.append(conversation.export_button)
        assert [button.x() for button in row] == sorted(button.x() for button in row)
        assert window.mode_combo.y() == window.pair_combo.y()
    finally:
        window.close()
        application.setFont(system)


def test_the_check_reports_cut_text_outside_a_scroll_area(window) -> None:
    """Known-positive control: a squeezed button is reported, a scrolled-away one is not."""
    settle(window, 850, 560)
    assert elided(window) == []
    window.start_button.setMaximumWidth(30)
    settle(window, 850, 560)
    assert any("Start" in item for item in elided(window))
    window.start_button.setMaximumWidth(16_777_215)


def test_start_stop_and_the_strip_stay_outside_the_scroll_areas(window) -> None:
    from lianiq.ui.shell.scroll import scroll_area_of
    from tests.ui._language_helpers import start

    start(window)
    for control in (
        window.start_button,
        window.stop_button,
        window.session_strip,
        window.call_bridge_panel.start_button,
        window.call_bridge_panel.stop_button,
    ):
        assert scroll_area_of(control) is None
    assert in_view(window.start_button, window) and in_view(window.stop_button, window)
    for workspace, inside in (
        (WorkspaceId.CONVERSATION, window.source_text),
        (WorkspaceId.CALL_BRIDGE, window.call_bridge_panel.enabled_checkbox),
        (WorkspaceId.SETTINGS, window.settings.readiness_field),
    ):
        assert scroll_area_of(inside) is not None, workspace


def test_the_readiness_summary_is_not_cut_at_850_by_560(window) -> None:
    """WI-02 advisory: the Call Bridge row of the readiness summary was clipped at 850×560."""
    window.show_workspace(WorkspaceId.SETTINGS)
    settle(window, 850, 560)
    field = window.settings.readiness_field
    assert "Call Bridge: " in field.text()
    # The long row wraps inside the page: all of it shown, no sideways scrolling.
    assert field.wordWrap() and field.height() >= field.heightForWidth(field.width())
    area = window.settings.readiness_field.parentWidget()
    while area.objectName() != "workspaceScroll":
        area = area.parentWidget()
    assert area.widget().width() <= area.viewport().width()
    assert elided(window) == []
