"""Fixes for the WI-08 native verification findings (CAP-0169, lianiq#69).

- DEF-01 / E-09: closing the window never destroys a migrated or saved routing, whether or
  not a language pair is ready.
- DEV-01: at the default window width the held-turn buttons show their full labels.
- DEV-02: at the default window width the closed *Language pair* and *Conversation
  direction* combos show their full selected value.

The layout checks compare each control's width with its size hint. The offscreen platform has
no font database, so they load the Windows UI font (Segoe UI) to measure real text widths.
Offscreen they are code evidence only; the same checks run on the native ``windows``
platform for WI-08 evidence (``QT_QPA_PLATFORM=windows``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import lianiq.config as config_module
from lianiq.audio.devices import AudioDevice
from lianiq.config import AppConfig
from lianiq.languages import LanguageId
from tests.test_requirement_scoped_loading import build_window, spies  # noqa: F401
from tests.ui.test_main_window_languages import start, submit, transcript, wait_until

DE = LanguageId("de")
ZH = LanguageId("zh-Hans")
REPO_ROOT = Path(__file__).resolve().parents[2]
REPO_DEFAULT = REPO_ROOT / "config" / "settings.json"
LEGACY_LOCAL_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "settings" / "legacy-v1.local.json"
DEFAULT_WIDTH, DEFAULT_HEIGHT = 1120, 720
# Device names as long as real Windows endpoint names.
LONG_DEVICES = [
    AudioDevice(
        0, "Microphone Array (Intel® Smart Sound Technology for Digital Microphones)", 1, 0
    ),
    AudioDevice(1, "Speakers (Realtek(R) Audio) — Headphones and Line Out Combined Jack", 0, 2),
]


@pytest.fixture
def settings_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The D-04 fixture as ``settings.local.json`` next to the shipped default (E-09)."""
    folder = tmp_path / "config"
    folder.mkdir()
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", folder / "settings.json")
    monkeypatch.setattr(config_module, "LOCAL_CONFIG_PATH", folder / "settings.local.json")
    (folder / "settings.json").write_bytes(REPO_DEFAULT.read_bytes())
    (folder / "settings.local.json").write_bytes(LEGACY_LOCAL_FIXTURE.read_bytes())
    return folder


def migrated_window(tmp_path, monkeypatch, request, *, provisioned: bool):
    """A window whose language settings come from the migrated D-04 fixture."""
    migrated = AppConfig.load()
    assert (migrated.languages.routing, migrated.languages.fixed_source) == ("fixed", "zh-Hans")

    def use_migrated_languages(config, _root) -> None:
        config.languages = migrated.languages

    window = build_window(
        tmp_path, monkeypatch, provisioned=provisioned, configure=use_migrated_languages
    )
    window.persist_settings = True  # E-09 closes the real window, which saves settings
    request.addfinalizer(window.close)
    return window


def saved_languages(folder: Path) -> dict:
    saved = json.loads((folder / "settings.local.json").read_text(encoding="utf-8"))
    assert saved["schema_version"] == 2
    return saved["languages"]


# DEF-01 / E-09 ----------------------------------------------------------------------------


@pytest.mark.parametrize("provisioned", [False, True], ids=["no-ready-pair", "ready-pair"])
def test_def01_e09_close_keeps_the_migrated_routing(
    tmp_path,
    monkeypatch,
    request,
    spies,  # noqa: F811
    settings_files,
    provisioned,
) -> None:
    window = migrated_window(tmp_path, monkeypatch, request, provisioned=provisioned)
    assert (window.current_pair() is not None) is provisioned

    window.close()  # change nothing, then close

    languages = saved_languages(settings_files)
    assert languages["routing"] == "fixed"
    assert languages["fixed_source"] == "zh-Hans"
    assert languages["output"] == "spoken"
    backup = settings_files / "settings.local.v1.json"
    assert backup.read_bytes() == LEGACY_LOCAL_FIXTURE.read_bytes()


@pytest.mark.parametrize(
    ("label", "routing", "fixed_source"),
    [
        ("German → Mandarin (Simplified)", "fixed", "de"),
        ("Automatic (German ↔ Mandarin (Simplified))", "bidirectional", None),
    ],
)
def test_def01_close_still_saves_a_routing_the_user_chose(
    tmp_path,
    monkeypatch,
    request,
    spies,  # noqa: F811
    settings_files,
    label,
    routing,
    fixed_source,
) -> None:
    window = migrated_window(tmp_path, monkeypatch, request, provisioned=True)
    window.mode_combo.setCurrentIndex(window.mode_combo.findText(label))

    window.close()

    languages = saved_languages(settings_files)
    assert (languages["routing"], languages["fixed_source"]) == (routing, fixed_source)


# DEV-01 / DEV-02: no clipping at the default window width ---------------------------------


def clipped(container) -> list[str]:
    """Visible controls in ``container`` narrower than their size hint or outside it."""
    from PySide6.QtWidgets import QAbstractButton, QComboBox, QLabel

    found = []
    widgets = [
        w for kind in (QAbstractButton, QComboBox, QLabel) for w in container.findChildren(kind)
    ]
    for widget in widgets:
        if not widget.isVisibleTo(container) or widget is getattr(container, "transcript_label", 0):
            continue
        left = widget.mapTo(container, widget.rect().topLeft()).x()
        inside = left >= 0 and left + widget.width() <= container.width()
        if not inside or widget.width() < widget.sizeHint().width():
            text = widget.currentText() if isinstance(widget, QComboBox) else widget.text()
            found.append(f"{text!r}: {widget.width()} < {widget.sizeHint().width()}")
    return found


WINDOWS_UI_FONT = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "segoeui.ttf"


@pytest.fixture(autouse=True)
def _load_windows_ui_font() -> None:
    """Register Segoe UI before any window is built, so no test depends on test order."""
    pytest.importorskip("PySide6")
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    if QApplication.platformName() == "offscreen" and WINDOWS_UI_FONT.is_file():
        assert QFontDatabase.addApplicationFont(str(WINDOWS_UI_FONT)) >= 0


def use_windows_ui_font(window) -> None:
    """Measure with Segoe UI, the native Windows UI font, also on the offscreen platform."""
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    if QApplication.platformName() != "offscreen":
        return
    if not WINDOWS_UI_FONT.is_file():
        pytest.skip("Segoe UI is not installed; widths need the Windows UI font")
    font = QFont(window.font())
    font.setFamily("Segoe UI")
    window.setFont(font)


def show_at_default_width(window) -> None:
    from PySide6.QtTest import QTest

    use_windows_ui_font(window)
    window.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)
    QTest.qWait(50)
    assert window.width() == DEFAULT_WIDTH


def test_dev01_held_turn_buttons_show_their_full_labels_at_the_default_width(
    tmp_path,
    monkeypatch,
    request,
    spies,  # noqa: F811
) -> None:
    from PySide6.QtTest import QTest

    window = build_window(tmp_path, monkeypatch)
    request.addfinalizer(window.close)
    show_at_default_width(window)
    start(window)
    long_text = "word " * 50
    submit(window, spies, transcript(long_text, "en"))
    submit(window, spies, transcript("Second unclear turn", "en"))
    bar = window.held_turn_bar
    assert wait_until(lambda: bar.isVisible() and bar.counter_label.isVisible())
    show_at_default_width(window)

    assert clipped(bar) == []
    buttons = [*bar.translate_buttons.values(), bar.discard_button]
    assert [button.text() for button in buttons] == [
        "Translate as German",
        "Translate as Mandarin (Simplified)",
        "Discard",
    ]
    # The excerpt yields the space: elided to what is left, full text in the tooltip.
    shown, quoted = bar.transcript_label.text(), bar.excerpt
    assert len(quoted.strip("“”")) == 120
    assert shown.endswith("…") and quoted.startswith(shown[:-1])
    assert bar.transcript_label.toolTip() == long_text
    assert excerpt_fits(bar)
    # The excerpt refits when the window is resized: wider shows more, back shows less.
    window.resize(1600, DEFAULT_HEIGHT)
    QTest.qWait(50)
    assert excerpt_fits(bar)
    assert len(bar.transcript_label.text()) > len(shown)
    show_at_default_width(window)
    assert excerpt_fits(bar)
    assert bar.transcript_label.text() == shown
    assert clipped(bar) == []
    window.stop_listening()


def excerpt_fits(bar) -> bool:
    label = bar.transcript_label
    text = label.text()
    return (
        bool(text) and label.fontMetrics().horizontalAdvance(text) <= label.contentsRect().width()
    )


@pytest.mark.parametrize("devices", [None, LONG_DEVICES], ids=["test-devices", "long-names"])
def test_dev02_language_combos_show_the_full_selected_value_at_the_default_width(
    tmp_path,
    monkeypatch,
    request,
    spies,  # noqa: F811
    devices,
) -> None:
    import lianiq.ui.main_window as main_window_module

    window = build_window(tmp_path, monkeypatch)
    request.addfinalizer(window.close)
    if devices is not None:
        monkeypatch.setattr(main_window_module, "list_audio_devices", lambda: list(devices))
        window._load_devices()

    for index in range(window.mode_combo.count()):
        window.mode_combo.setCurrentIndex(index)
        show_at_default_width(window)
        controls = (window.pair_combo, window.mode_combo, window.tts_checkbox, window.gpu_checkbox)
        assert [
            f"{control.accessibleName() or control.objectName()}: {control.width()}"
            for control in controls
            if control.width() < control.sizeHint().width()
            or control.mapTo(window, control.rect().topRight()).x() > window.width()
        ] == []
        # The device and model combos may shorten their text, but stay readable.
        for combo in (window.input_combo, window.output_combo, window.model_combo):
            assert combo.width() >= combo.minimumSizeHint().width() > 0
