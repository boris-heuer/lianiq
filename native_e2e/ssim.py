"""Screenshot comparison for the SHOT row (CAP-0174 contract §1, §6 and N-03).

``ssim`` is windowed SSIM on grey images: local SSIM over every 8×8 window (stride 1,
standard constants), and the score is the *minimum* local SSIM. A mean over the windows
would hide a changed 40×40 region of the 1400×1000 reference (it affects about 0.2 % of
the windows), so AC-04 needs the worst window. SHOT passes at ``THRESHOLD`` or above and is
otherwise ``pending`` with the comparison sheet until the PO signs off.

``comparison_sheet`` writes old | new | difference as three panels of equal size; images of
different size are padded with black, and the difference panel marks each changed pixel in
``DIFF_COLOUR`` over a dimmed grey copy. numpy for the arithmetic, QImage for PNG I/O.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

WINDOW = 8
THRESHOLD = 0.990
DIFF_COLOUR = 0xFFFF0000  # opaque red as QColor.rgb()
_C1 = (0.01 * 255) ** 2
_C2 = (0.03 * 255) ** 2
_OPAQUE = np.uint32(0xFF000000)


def ssim(a: Path, b: Path) -> float:
    """Return the minimum 8×8-window SSIM of two images; 0.0 when their sizes differ."""
    x, y = _grey(_rgb32(a)), _grey(_rgb32(b))
    if x.shape != y.shape:
        return 0.0
    size = min(WINDOW, *x.shape)
    count = size * size
    mean_x, mean_y = _window_sums(x, size) / count, _window_sums(y, size) / count
    var_x = _window_sums(x * x, size) / count - mean_x * mean_x
    var_y = _window_sums(y * y, size) / count - mean_y * mean_y
    cov = _window_sums(x * y, size) / count - mean_x * mean_y
    local = ((2 * mean_x * mean_y + _C1) * (2 * cov + _C2)) / (
        (mean_x * mean_x + mean_y * mean_y + _C1) * (var_x + var_y + _C2)
    )
    return float(local.min())


def comparison_sheet(old: Path, new: Path, out: Path) -> None:
    """Write ``out`` as a PNG with the panels old, new and difference side by side."""
    from PySide6.QtGui import QImage

    a, b = _rgb32(old), _rgb32(new)
    height, width = max(a.shape[0], b.shape[0]), max(a.shape[1], b.shape[1])
    panel_a, valid_a = _pad(a, height, width)
    panel_b, valid_b = _pad(b, height, width)
    changed = (valid_a != valid_b) | (valid_a & valid_b & (panel_a != panel_b))
    base = np.where(valid_b, _grey(panel_b), _grey(panel_a))
    dim = (base * 0.5 + 64).astype(np.uint32)
    diff = _OPAQUE | (dim << 16) | (dim << 8) | dim
    diff[changed] = DIFF_COLOUR
    sheet = np.ascontiguousarray(np.hstack([panel_a, panel_b, diff]), dtype=np.uint32)
    data = sheet.tobytes()
    image = QImage(data, 3 * width, height, 3 * width * 4, QImage.Format.Format_RGB32)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(out), "PNG"):
        raise OSError(f"comparison sheet could not be written: {out.name}")


def _rgb32(path: Path) -> np.ndarray:
    from PySide6.QtGui import QImage

    image = QImage(str(path))
    if image.isNull():
        raise ValueError(f"unreadable image: {Path(path).name}")
    image = image.convertToFormat(QImage.Format.Format_RGB32)
    stride = image.bytesPerLine() // 4
    pixels = np.frombuffer(image.constBits(), dtype=np.uint32, count=image.height() * stride)
    return pixels.reshape(image.height(), stride)[:, : image.width()].copy()


def _grey(rgb: np.ndarray) -> np.ndarray:
    red = (rgb >> 16) & 0xFF
    green = (rgb >> 8) & 0xFF
    blue = rgb & 0xFF
    return (red * 11 + green * 16 + blue * 5).astype(np.float64) / 32  # qGray weights


def _window_sums(values: np.ndarray, size: int) -> np.ndarray:
    total = np.zeros((values.shape[0] + 1, values.shape[1] + 1))
    total[1:, 1:] = values.cumsum(axis=0).cumsum(axis=1)
    return total[size:, size:] - total[:-size, size:] - total[size:, :-size] + total[:-size, :-size]


def _pad(rgb: np.ndarray, height: int, width: int) -> tuple[np.ndarray, np.ndarray]:
    panel = np.full((height, width), _OPAQUE, dtype=np.uint32)
    valid = np.zeros((height, width), dtype=bool)
    panel[: rgb.shape[0], : rgb.shape[1]] = rgb
    valid[: rgb.shape[0], : rgb.shape[1]] = True
    return panel, valid
