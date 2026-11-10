"""AC-32 (UI): long, CJK, diacritic and RTL labels; no flag glyphs (CAP-0168 WI-05).

The window runs over German/Mandarin plus fixture-backed English, Spanish and French entries
(``tests/languages/synthetic.py``: a 60-character name, diacritics, CJK) and an RTL entry.
Labels and panels render without cut actions at 850×560 and 1280×720, RTL paragraphs read
right to left, and no UI string or shown text contains a flag glyph. Also the A3 advisory:
banner labels take the banner's background. Offscreen code evidence.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.ui import strings, theme
from lianiq.ui.shell.workspaces import WorkspaceId
from tests._spy_window import build_window, spies  # noqa: F401
from tests.languages.synthetic import LONG_NAME, PRESENTATION_NAMES, presentation_registry
from tests.ui._language_helpers import items, start, submit, transcript, visible_texts, wait_until
from tests.ui._layout_checks import SHOWN, elided, load_ui_fonts, settle

ARABIC = "مرحبا بكم، هذه فقرة من اليمين إلى اليسار."
# Regional indicators, the flag emoji and the tag characters of subdivision flags.
FLAG_RANGES = ((0x1F1E6, 0x1F1FF), (0xE0020, 0xE007F))
FLAG_POINTS = frozenset({0x1F3F3, 0x1F3F4, 0x1F38C, 0x1F6A9, 0x1F3C1})


def has_flag(text: str) -> bool:
    return any(
        point in FLAG_POINTS or any(low <= point <= high for low, high in FLAG_RANGES)
        for point in map(ord, text)
    )


@pytest.fixture
def window(tmp_path, spies, monkeypatch):  # noqa: F811
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    load_ui_fonts()
    window = build_window(tmp_path, monkeypatch, registry=presentation_registry())
    theme.apply(window, high_contrast=False)
    yield window
    window.stop_listening()
    window.close()


def test_ac32_the_fixture_entries_are_listed_by_their_names(window) -> None:
    assert len(LONG_NAME) == 60
    listed = items(window.pair_combo)
    assert listed[0] == "German ↔ Mandarin (Simplified)"
    for name in PRESENTATION_NAMES.values():
        assert f"{name} {strings.PAIR_PLANNED_SUFFIX}" in listed


def fits_current_text(combo) -> bool:
    """The closed combo is as wide as one holding only its current entry."""
    from PySide6.QtWidgets import QComboBox

    probe = QComboBox()
    probe.setFont(combo.font())
    probe.setStyleSheet(combo.window().styleSheet())
    probe.addItem(combo.currentText())
    probe.ensurePolished()
    return combo.width() >= probe.sizeHint().width()


@pytest.mark.parametrize("size", [(850, 560), (1280, 720)])
def test_ac32_long_labels_never_cut_an_action(window, spies, size) -> None:  # noqa: F811
    start(window)
    submit(window, spies, transcript("这是一个很长的中文句子，用来检查标签和面板。", "zh-Hans"))
    held = "Ünklare Sprache — ça va? 请您再慢慢地重复一遍最后一句话，因为线路的噪音非常大。"
    submit(window, spies, transcript(held, "en"))  # an unclear language: held
    assert wait_until(window.held_turn_bar.isVisible)
    window.show_error(f"{LONG_NAME} · {PRESENTATION_NAMES['qac']}")  # a banner with both
    for workspace in SHOWN:
        window.show_workspace(workspace)
        settle(window, *size)
        assert (window.width(), window.height()) == size
        assert elided(window) == [], workspace
    window.show_workspace(WorkspaceId.CONVERSATION)
    settle(window, *size)
    assert fits_current_text(window.pair_combo) and fits_current_text(window.mode_combo)
    assert window.banners[WorkspaceId.CONVERSATION].isVisible()
    bar = window.held_turn_bar  # no sideways scrolling: the bar stacks its buttons if needed
    assert bar.mapTo(window, bar.rect().topRight()).x() <= window.width()


def test_ac32_rtl_paragraphs_read_right_to_left(window) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QTextCursor

    settle(window, 1280, 720)
    panel = window.target_panel
    panel.append_line(f"{ARABIC}\n")
    panel.append_line("German: Guten Tag\n")
    text = panel.text
    document = text.document()
    assert document.defaultTextOption().textDirection() == Qt.LayoutDirection.LayoutDirectionAuto
    rtl, ltr = document.findBlock(0), document.findBlock(document.toPlainText().index("German"))
    assert rtl.textDirection() == Qt.LayoutDirection.RightToLeft
    assert ltr.textDirection() == Qt.LayoutDirection.LeftToRight
    # The RTL paragraph starts at the right edge, the LTR one at the left.
    middle = text.viewport().width() / 2
    assert text.cursorRect(QTextCursor(rtl)).x() > middle
    assert text.cursorRect(QTextCursor(ltr)).x() < middle


def test_ac32_no_flag_glyphs_in_ui_strings_or_shown_text(window) -> None:
    assert has_flag("German 🇩🇪") and has_flag("🏴")  # known-positive controls
    assert not has_flag("German 中文 مرحبا")  # known-negative control
    constants = [value for name, value in vars(strings).items() if name.isupper()]
    texts = [value for value in constants if isinstance(value, str)]
    assert len(texts) > 100
    for workspace in SHOWN:
        window.show_workspace(workspace)
        texts += visible_texts(window)
    texts += [item.label for item in window.navigation.entries]
    assert [text for text in texts if has_flag(text)] == []


def test_no_fixed_pixel_height_on_text_bearing_widgets(window) -> None:
    from PySide6.QtWidgets import QAbstractButton, QComboBox, QLabel, QPlainTextEdit

    kinds = (QAbstractButton, QComboBox, QLabel, QPlainTextEdit)
    fixed = [
        f"{type(widget).__name__} {widget.objectName()}"
        for kind in kinds
        for widget in window.findChildren(kind)
        if widget.minimumHeight() == widget.maximumHeight()
    ]
    assert fixed == []


def test_a3_banner_labels_take_the_banner_background(window) -> None:
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QColor

    window.show_error("Something failed")
    banner = window.banners[WorkspaceId.CONVERSATION]
    settle(window, 1280, 720)
    image = banner.grab().toImage()
    ratio = image.devicePixelRatio()
    expected = QColor(theme.COLORS["warn_bg"])
    for label in (banner.title_label, banner.detail_label, banner.icon_label):
        corner = label.mapTo(banner, QPoint(label.width() - 2, label.height() - 2))
        drawn = image.pixelColor(int(corner.x() * ratio), int(corner.y() * ratio))
        assert drawn == expected, (label.objectName(), drawn.name())
