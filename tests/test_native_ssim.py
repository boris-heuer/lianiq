"""Windowed SSIM and the comparison sheet for the SHOT row (CAP-0174 AC-04, N-03)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QImage

from native_e2e import ssim as ssim_module
from native_e2e.ssim import THRESHOLD, WINDOW, comparison_sheet, ssim

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "docs" / "assets" / "application-ui.png"


def _changed_copy(source: Path, out: Path, left: int, top: int, size: int = 40) -> Path:
    image = QImage(str(source)).convertToFormat(QImage.Format.Format_RGB32)
    for x in range(left, left + size):
        for y in range(top, top + size):
            colour = image.pixelColor(x, y)
            image.setPixelColor(
                x, y, QColor(255 - colour.red(), 255 - colour.green(), 255 - colour.blue())
            )
    assert image.save(str(out), "PNG")
    return out


def _solid(out: Path, width: int, height: int, grey: int) -> Path:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(grey, grey, grey))
    assert image.save(str(out), "PNG")
    return out


def test_the_constants_are_the_fixed_test_data() -> None:
    assert (WINDOW, THRESHOLD) == (8, 0.990)


def test_identical_images_score_exactly_one(tmp_path: Path) -> None:
    copy = tmp_path / "copy.png"
    copy.write_bytes(REFERENCE.read_bytes())

    assert ssim(REFERENCE, copy) == 1.0
    assert ssim(REFERENCE, REFERENCE) == 1.0


def test_one_changed_40_px_region_of_the_reference_falls_below_the_threshold(
    tmp_path: Path,
) -> None:
    image = QImage(str(REFERENCE))
    changed = _changed_copy(
        REFERENCE, tmp_path / "changed.png", image.width() // 2, image.height() // 2
    )

    assert ssim(REFERENCE, changed) < THRESHOLD


def test_a_flat_region_change_also_falls_below_the_threshold(tmp_path: Path) -> None:
    flat = _solid(tmp_path / "flat.png", 200, 120, 240)
    changed = _changed_copy(flat, tmp_path / "changed.png", 10, 10)

    assert ssim(flat, changed) < THRESHOLD


def test_images_of_different_size_score_zero(tmp_path: Path) -> None:
    small = _solid(tmp_path / "small.png", 40, 40, 128)
    large = _solid(tmp_path / "large.png", 48, 40, 128)

    assert ssim(small, large) == 0.0


def test_an_unreadable_image_raises(tmp_path: Path) -> None:
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not a png")

    with pytest.raises(ValueError):
        ssim(REFERENCE, broken)
    with pytest.raises(ValueError):
        ssim(REFERENCE, tmp_path / "missing.png")


def test_the_comparison_sheet_has_three_panels_of_equal_size(tmp_path: Path) -> None:
    reference = QImage(str(REFERENCE))
    width, height = reference.width(), reference.height()
    changed = _changed_copy(REFERENCE, tmp_path / "changed.png", 100, 120)
    out = tmp_path / "compare" / "application-ui.png"

    comparison_sheet(REFERENCE, changed, out)

    sheet = QImage(str(out))
    assert (sheet.width(), sheet.height()) == (3 * width, height)
    new = QImage(str(changed))
    for x, y in ((5, 5), (110, 130), (width - 1, height - 1)):
        assert sheet.pixelColor(x, y).rgb() == reference.pixelColor(x, y).rgb()
        assert sheet.pixelColor(width + x, y).rgb() == new.pixelColor(x, y).rgb()
    assert sheet.pixelColor(2 * width + 110, 130).rgb() == ssim_module.DIFF_COLOUR
    assert sheet.pixelColor(2 * width + 5, 5).rgb() != ssim_module.DIFF_COLOUR


def test_the_comparison_sheet_pads_images_of_different_size(tmp_path: Path) -> None:
    old = _solid(tmp_path / "old.png", 30, 20, 100)
    new = _solid(tmp_path / "new.png", 40, 10, 100)
    out = tmp_path / "sheet.png"

    comparison_sheet(old, new, out)

    sheet = QImage(str(out))
    assert (sheet.width(), sheet.height()) == (3 * 40, 20)
    assert sheet.pixelColor(2 * 40 + 35, 5).rgb() == ssim_module.DIFF_COLOUR  # only in new
    assert sheet.pixelColor(2 * 40 + 5, 15).rgb() == ssim_module.DIFF_COLOUR  # only in old
    assert sheet.pixelColor(2 * 40 + 35, 15).rgb() != ssim_module.DIFF_COLOUR  # in neither
