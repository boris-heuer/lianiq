"""The presentation tokens and stylesheet (CAP-0168 WI-05; spec §2.3.7, §9 T2).

AC-31 (Unit): every text/background pair has contrast ≥ 4.5:1 and every focus or control
boundary ≥ 3:1 against its surface. Also: the tokens are the ``docs/ui/target/styles.css``
values, the stylesheet uses only tokens and point sizes relative to the system font, and
the high-contrast switch (Qt contrast preference, else ``SPI_GETHIGHCONTRAST``).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from lianiq.ui import theme

STYLES_CSS = Path(__file__).resolve().parents[1] / "docs" / "ui" / "target" / "styles.css"
# Token name in theme.py → custom property (or literal) in styles.css.
CSS_TOKENS = {
    "bg": "--bg",
    "panel": "--panel",
    "well": "--well",
    "line": "--line",
    "text": "--text",
    "muted": "--muted",
    "accent": "--accent",
    "primary": "--primary",
    "mint": "--mint",
    "warn": "--warn",
    "bad": "--bad",
    "focus": "--focus",
}


def test_ac31_text_pairs_reach_4_5_to_1() -> None:
    low = {
        f"{text} on {background}": round(ratio, 2)
        for text, background in theme.TEXT_PAIRS
        if (ratio := theme.contrast_ratio(theme.COLORS[text], theme.COLORS[background])) < 4.5
    }
    assert low == {}
    assert len(theme.TEXT_PAIRS) >= 10


def test_ac31_focus_and_control_boundaries_reach_3_to_1() -> None:
    low = {
        f"{line} on {surface}": round(ratio, 2)
        for line, surface in theme.BOUNDARY_PAIRS
        if (ratio := theme.contrast_ratio(theme.COLORS[line], theme.COLORS[surface])) < 3.0
    }
    assert low == {}
    surfaces = {surface for line, surface in theme.BOUNDARY_PAIRS if line == "focus"}
    assert {"bg", "panel", "well", "sidebar", "warn_bg", "bad_bg"} <= surfaces


def test_ac31_contrast_formula_matches_wcag() -> None:
    assert theme.contrast_ratio("#ffffff", "#000000") == pytest.approx(21.0)
    assert theme.contrast_ratio("#777777", "#777777") == pytest.approx(1.0)
    # The CSS separator colour is below 3:1, so it never draws a control boundary.
    assert theme.contrast_ratio(theme.COLORS["line"], theme.COLORS["bg"]) < 3.0


def test_ac31_control_boundaries_use_the_boundary_token_not_the_separator() -> None:
    sheet = theme.stylesheet(9.0)
    for rule in re.findall(r"([^{}]+)\{([^}]*)\}", sheet):
        selector, body = rule
        if theme.COLORS["line"] in body:
            assert "navigationSidebar" in selector or "sessionStrip" in selector, selector


def test_tokens_are_the_design_intent_values() -> None:
    css = STYLES_CSS.read_text(encoding="utf-8")
    for token, name in CSS_TOKENS.items():
        match = re.search(rf"{re.escape(name)}:(#[0-9a-f]{{6}})", css)
        assert match and match.group(1) == theme.COLORS[token], token
    for literal in ("#0c131e", "#243551", "#20324a", "#a5b0c0", "#19212c", "#558cf1"):
        assert literal in css and literal in theme.COLORS.values()
    assert "--font:15px" in css and theme.TYPE_PX["body"] == 15
    assert theme.SPACING == (4, 8, 12, 16, 24) and theme.FOCUS_WIDTH == 2


def test_the_stylesheet_uses_only_tokens_and_point_sizes() -> None:
    sheet = theme.stylesheet(9.0)
    assert set(re.findall(r"#[0-9a-fA-F]{6}\b", sheet)) <= set(theme.COLORS.values())
    assert not re.search(r"font-size:\s*[\d.]+px", sheet)
    assert "font-size: 11.25pt" in sheet  # 15 px over a 9 pt system font
    assert f"{theme.FOCUS_WIDTH}px solid {theme.COLORS['focus']}" in sheet


def test_type_sizes_follow_the_system_font() -> None:
    # Windows "Make text bigger" 150 % turns the 9 pt system font into 13.5 pt.
    assert theme.point_size(15, 9.0) == 11.25
    assert theme.point_size(15, 13.5) == 16.88
    assert "font-size: 16.88pt" in theme.stylesheet(13.5)


def test_t2_high_contrast_uses_the_qt_preference(monkeypatch) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication

    class Accessibility:
        preference = Qt.ContrastPreference.HighContrast

        def contrastPreference(self):
            return self.preference

    class Hints:
        accessibility = Accessibility

    monkeypatch.setattr(QGuiApplication, "styleHints", staticmethod(lambda: Hints()))
    monkeypatch.setattr(theme, "windows_high_contrast", lambda: False)
    assert theme.high_contrast_active() is True
    Accessibility.preference = Qt.ContrastPreference.NoPreference
    assert theme.high_contrast_active() is False
    monkeypatch.setattr(theme, "windows_high_contrast", lambda: True)  # SPI_GETHIGHCONTRAST
    assert theme.high_contrast_active() is True


def test_t2_spi_getHighContrast_is_read_on_windows() -> None:
    value = theme.windows_high_contrast()
    assert isinstance(value, bool)
    if sys.platform != "win32":
        assert value is False


def test_apply_sets_fonts_and_drops_the_stylesheet_in_high_contrast(monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication, QWidget

    QApplication.instance() or QApplication([])
    widget = QWidget()
    assert theme.apply(widget, high_contrast=False) is False
    assert widget.font().families()[:2] == ["Segoe UI", "Microsoft YaHei UI"]
    assert widget.styleSheet() == theme.stylesheet()
    assert theme.apply(widget, high_contrast=True) is True
    assert widget.styleSheet() == "" and widget.property("highContrast") is True
    assert widget.palette() == QApplication.palette()  # the system palette
    monkeypatch.setattr(theme, "high_contrast_active", lambda: True)
    assert theme.apply(widget) is True
