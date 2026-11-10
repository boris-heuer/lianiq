"""The presentation baseline (CAP-0168 spec §2.3.7, §2.5): tokens, one stylesheet, fonts.

Replaces ``MainWindowLayout._apply_style``. The colour, spacing, radius and type tokens come
from ``docs/ui/target/styles.css``; ``stylesheet`` builds the one stylesheet from them, with a
visible 2 px focus outline on every focusable widget. Type sizes are points relative to the
system font (CSS px over the 12 px of a 9 pt system font), so Windows text scaling and DPI
scaling both enlarge them. Fonts: Segoe UI, Microsoft YaHei UI, then the system fallback.

Control boundaries use ``muted``: the CSS draws them in ``line``, which is below the AC-31
3:1 boundary contrast; ``line`` stays for decorative separators only.

Windows high contrast (spec §9 T2): Qt's ``QAccessibilityHints.contrastPreference`` where the
platform reports it, else ``SPI_GETHIGHCONTRAST``. While it is on, no custom stylesheet is
set, so the system palette and the native focus rectangle are used.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget

COLORS = {
    "bg": "#101722",
    "panel": "#17212f",
    "well": "#111a26",
    "sidebar": "#0c131e",
    "selected": "#243551",
    "hover": "#20324a",
    "line": "#344457",
    "text": "#edf3fb",
    "muted": "#afbdcf",
    "accent": "#5798ff",
    "primary": "#225cbb",
    "primary_line": "#558cf1",
    "disabled_text": "#a5b0c0",
    "disabled_bg": "#19212c",
    "mint": "#88dfc1",
    "warn": "#ffcf87",
    "warn_bg": "#30291f",
    "bad": "#ffacb1",
    "bad_bg": "#301f2a",
    "focus": "#bcd7ff",
}
SPACING = (4, 8, 12, 16, 24)
RADII = {"control": 8, "panel": 12}
# CSS px of styles.css: body (--font), small text, section title (h2), transcript.
TYPE_PX = {"body": 15, "small": 12, "title": 19, "transcript": 22}
SYSTEM_FONT_PX = 12  # a 9 pt system font at 96 dpi
FOCUS_WIDTH = 2
FONT_FAMILIES = ("Segoe UI", "Microsoft YaHei UI")

# Text on its background (≥ 4.5:1) and boundaries on their surface (≥ 3:1), AC-31.
TEXT_PAIRS = (
    ("text", "bg"),
    ("text", "panel"),
    ("text", "well"),
    ("text", "sidebar"),
    ("text", "selected"),
    ("text", "hover"),
    ("text", "primary"),
    ("muted", "bg"),
    ("muted", "panel"),
    ("disabled_text", "disabled_bg"),
    ("disabled_text", "sidebar"),
    ("mint", "well"),
    ("warn", "warn_bg"),
    ("bad", "bad_bg"),
)
BOUNDARY_PAIRS = (
    *(("focus", surface) for surface in ("bg", "panel", "well", "sidebar", "selected")),
    ("focus", "warn_bg"),
    ("focus", "bad_bg"),
    ("muted", "bg"),
    ("muted", "panel"),
    ("muted", "well"),
    ("accent", "sidebar"),
    ("accent", "selected"),
    ("primary_line", "bg"),
    ("mint", "well"),
    ("warn", "warn_bg"),
    ("bad", "bad_bg"),
)

SPI_GETHIGHCONTRAST = 0x0042
HCF_HIGHCONTRASTON = 0x00000001


def relative_luminance(color: str) -> float:
    """WCAG 2.x relative luminance of ``#rrggbb``."""
    channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(first: str, second: str) -> float:
    lighter, darker = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def system_point_size() -> float:
    size = QApplication.font().pointSizeF()
    return size if size > 0 else 9.0


def point_size(px: int, base: float | None = None) -> float:
    """``px`` of the CSS as points relative to the system font."""
    return round((base or system_point_size()) * px / SYSTEM_FONT_PX, 2)


def stylesheet(base: float | None = None) -> str:
    c = COLORS
    pt = {name: point_size(px, base) for name, px in TYPE_PX.items()}
    r, rp, f = RADII["control"], RADII["panel"], FOCUS_WIDTH
    return f"""
QMainWindow, QWidget {{ background: {c["bg"]}; color: {c["text"]}; font-size: {pt["body"]}pt; }}
QLabel, QCheckBox {{ background: transparent; }}
QToolTip {{ background: {c["panel"]}; color: {c["text"]}; border: 1px solid {c["muted"]}; }}
QFrame#navigationSidebar {{ background: {c["sidebar"]}; border-right: 1px solid {c["line"]}; }}
QFrame#navigationSidebar QToolButton {{ background: transparent; padding: {SPACING[1]}px;
    border: {f}px solid transparent; border-radius: {r}px; text-align: left; }}
QFrame#navigationSidebar QToolButton:checked {{ background: {c["selected"]};
    border-left: 3px solid {c["accent"]}; font-weight: 700; }}
QFrame#navigationSidebar QToolButton:disabled {{ color: {c["disabled_text"]}; }}
QFrame#sessionStrip {{ background: {c["panel"]}; border: 1px solid {c["line"]};
    border-radius: {r}px; }}
QScrollArea#workspaceScroll {{ border: 0; }}
QLabel#panelTitle {{ font-size: {pt["title"]}pt; font-weight: 600; color: {c["muted"]}; }}
QPlainTextEdit {{ background: {c["well"]}; border: 1px solid {c["muted"]}; border-radius: {rp}px;
    padding: {SPACING[2]}px; font-size: {pt["transcript"]}pt;
    selection-background-color: {c["primary"]}; selection-color: {c["text"]}; }}
QPlainTextEdit#diagnosticsText {{ font-size: {pt["small"]}pt; }}
QComboBox, QPushButton {{ background: {c["panel"]}; border: 1px solid {c["muted"]};
    border-radius: {r}px; padding: {SPACING[1]}px {SPACING[2]}px; }}
QComboBox QAbstractItemView {{ background: {c["panel"]};
    selection-background-color: {c["primary"]}; }}
QComboBox:hover, QPushButton:hover {{ border-color: {c["accent"]}; background: {c["hover"]}; }}
QPushButton#primaryButton {{ background: {c["primary"]}; border-color: {c["primary_line"]};
    font-weight: 600; }}
QPushButton:disabled, QComboBox:disabled, QPushButton#primaryButton:disabled {{
    color: {c["disabled_text"]}; background: {c["disabled_bg"]}; border-color: {c["muted"]};
    border-style: dashed; }}
QCheckBox, QLabel#readOnlyValue {{ border: {f}px solid transparent; border-radius: 4px;
    padding: 1px; }}
QProgressBar {{ background: {c["well"]}; border: 1px solid {c["muted"]}; border-radius: 5px; }}
QProgressBar::chunk {{ background: {c["mint"]}; border-radius: 4px; }}
QStatusBar {{ color: {c["muted"]}; font-size: {pt["small"]}pt; }}
QFrame#noticeBanner {{ border-radius: {r}px; border: 1px solid {c["muted"]};
    background: {c["panel"]}; }}
QFrame#noticeBanner[severity="warning"] {{ border: {f}px solid {c["warn"]};
    background: {c["warn_bg"]}; }}
QFrame#noticeBanner[severity="blocking"] {{ border: {f}px solid {c["bad"]};
    background: {c["bad_bg"]}; }}
QLabel#noticeTitle {{ font-weight: 600; }}
QFrame#heldTurnBar {{ border: 1px solid {c["warn"]}; border-radius: {r}px;
    background: {c["warn_bg"]}; }}
QPushButton:focus, QPushButton#primaryButton:focus, QComboBox:focus {{
    border: {f}px solid {c["focus"]};
    padding: {SPACING[1] - 1}px {SPACING[2] - 1}px; }}
QPlainTextEdit:focus {{ border: {f}px solid {c["focus"]}; padding: {SPACING[2] - 1}px; }}
QCheckBox:focus, QLabel#readOnlyValue:focus, QFrame#navigationSidebar QToolButton:focus,
QFrame#noticeBanner:focus, QFrame#heldTurnBar:focus {{ border: {f}px solid {c["focus"]}; }}
"""


def high_contrast_active() -> bool:
    """Whether Windows high contrast (or the platform's high-contrast preference) is on."""
    hints = QGuiApplication.styleHints()
    accessibility = getattr(hints, "accessibility", None)
    preference = getattr(Qt, "ContrastPreference", None)
    if (
        accessibility is not None
        and preference is not None
        and accessibility().contrastPreference() == preference.HighContrast
    ):
        return True
    return windows_high_contrast()


def windows_high_contrast() -> bool:
    """``SPI_GETHIGHCONTRAST`` (``HCF_HIGHCONTRASTON``); ``False`` off Windows."""
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    class HighContrast(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("dwFlags", wintypes.DWORD),
            ("lpszDefaultScheme", wintypes.LPWSTR),
        ]

    value = HighContrast()
    value.cbSize = ctypes.sizeof(HighContrast)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    ok = user32.SystemParametersInfoW(SPI_GETHIGHCONTRAST, value.cbSize, ctypes.byref(value), 0)
    return bool(ok) and bool(value.dwFlags & HCF_HIGHCONTRASTON)


def apply(window: QWidget, high_contrast: bool | None = None) -> bool:
    """Set the font families and the stylesheet (none in high contrast); returns the mode."""
    contrast = high_contrast_active() if high_contrast is None else high_contrast
    font = QFont(window.font())
    font.setFamilies([*FONT_FAMILIES, *(f for f in font.families() if f not in FONT_FAMILIES)])
    window.setFont(font)
    window.setStyleSheet("" if contrast else stylesheet())
    window.setProperty("highContrast", contrast)
    return contrast


def follow_system(window: QWidget) -> None:
    """Re-apply when the platform's contrast preference changes (where Qt reports it)."""
    accessibility = getattr(QGuiApplication.styleHints(), "accessibility", None)
    signal = getattr(accessibility(), "contrastPreferenceChanged", None) if accessibility else None
    if signal is None:
        return

    def reapply(*_args) -> None:
        try:
            apply(window)
        except RuntimeError:  # the window was closed and deleted meanwhile
            signal.disconnect(reapply)

    signal.connect(reapply)
