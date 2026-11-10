"""The AC-29 matrix under one ``QT_SCALE_FACTOR`` (run as a subprocess by the matrix test).

Qt reads ``QT_SCALE_FACTOR`` once, when the application starts, so each factor needs its own
process. Prints one JSON line: the device pixel ratio and every problem found.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SIZES = ((850, 560), (1120, 720), (1280, 720), (1440, 900))
WORK_AREA = (800, 500)


def main() -> int:
    import pytest
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QApplication

    from tests._spy_window import build_window, install_spies
    from tests.ui._layout_checks import load_ui_fonts, matrix_problems

    application = QApplication.instance() or QApplication([])
    load_ui_fonts()
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as folder, pytest.MonkeyPatch.context() as patch:
        install_spies(patch)
        window = build_window(Path(folder), patch)
        ratio = window.devicePixelRatioF()
        try:
            for width, height in SIZES:
                problems += matrix_problems(window, width, height)
            # The window with its frame fits the work area; the minimum yields to it.
            window.fit_to_work_area(QRect(0, 0, *WORK_AREA))
            fitted = (window.width(), window.height())
            frame = window.frameGeometry()
            if not QRect(0, 0, *WORK_AREA).contains(frame) or fitted[0] < WORK_AREA[0] - 40:
                problems.append(f"window frame {frame} in the {WORK_AREA} work area")
            if (window.minimumWidth(), window.minimumHeight()) != fitted:
                problems.append(f"minimum {window.minimumSize()} above the fitted {fitted}")
            problems += matrix_problems(window, *fitted)
        finally:
            window.close()
    print(json.dumps({"ratio": ratio, "problems": problems}))
    application.processEvents()
    return 0


if __name__ == "__main__":
    sys.exit(main())
