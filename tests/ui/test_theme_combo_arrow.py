"""Combo box corners (PO SHOT review of native run 44267851808).

With only the frame styled, Windows 11 drew its native drop-down button over the right end
of every combo box, cutting off the rounded top-right and bottom-right corners. The theme
styles ``::drop-down`` transparent and borderless, so the frame's corners show, and draws
the arrow from a packaged SVG (Qt draws no arrow once ``::drop-down`` is styled).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from lianiq.ui import theme

ROOT = Path(__file__).resolve().parents[2]


def _rule(sheet: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", sheet)
    assert match, selector
    return match.group(1)


def test_drop_down_is_transparent_so_the_rounded_frame_shows() -> None:
    rule = _rule(theme.stylesheet(9.0), "QComboBox::drop-down")
    assert "border: 0" in rule
    assert "background: transparent" in rule
    assert "subcontrol-origin: padding" in rule


def test_down_arrow_uses_the_packaged_svg() -> None:
    rule = _rule(theme.stylesheet(9.0), "QComboBox::down-arrow")
    url = re.search(r'image: url\("([^"]+)"\)', rule)
    assert url and Path(url.group(1)) == theme.COMBO_ARROW
    assert theme.COMBO_ARROW.is_file()
    assert theme.COMBO_ARROW.read_text(encoding="utf-8").startswith("<svg")


def test_the_arrow_ships_in_the_wheel_and_the_pyinstaller_build() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "assets/*.svg" in project["tool"]["setuptools"]["package-data"]["lianiq.ui"]
    build = (ROOT / "scripts" / "build.ps1").read_text(encoding="utf-8")
    assert '--add-data "lianiq/ui/assets;lianiq/ui/assets"' in build
