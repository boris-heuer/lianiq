"""AC-01: every file under ``lianiq/ui/`` fits the 32 KiB publish limit (CAP-0168 WI-01).

Each file must stay at or below 32,768 bytes, so every UI change can be published through
the Factory SCM Gateway. The walk covers every file and extension under ``lianiq/ui/``;
only ``__pycache__`` is skipped, because Python writes it locally and it is never versioned.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

UI_PACKAGE = Path(__file__).resolve().parents[1] / "lianiq" / "ui"
LIMIT_BYTES = 32_768


def ui_files(root: Path = UI_PACKAGE) -> list[Path]:
    return [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.relative_to(root).parts
    ]


def test_ac01_every_ui_file_is_at_most_32_kib() -> None:
    files = ui_files()
    assert UI_PACKAGE / "main_window.py" in files  # the walk sees the package
    oversized = [
        f"{path.relative_to(UI_PACKAGE).as_posix()}: {path.stat().st_size} bytes"
        for path in files
        if path.stat().st_size > LIMIT_BYTES
    ]
    assert oversized == []


def test_ac01_the_walk_includes_every_extension_and_nested_package(tmp_path) -> None:
    (tmp_path / "workspaces").mkdir()
    (tmp_path / "workspaces" / "page.py").write_text("")
    (tmp_path / "styles.qss").write_text("")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "page.cpython-312.pyc").write_bytes(b"")

    names = [path.relative_to(tmp_path).as_posix() for path in ui_files(tmp_path)]

    assert names == ["styles.qss", "workspaces/page.py"]


def test_ac01_the_accessibility_module_no_longer_exists() -> None:
    assert not (UI_PACKAGE / "accessibility.py").exists()
    assert importlib.util.find_spec("lianiq.ui.accessibility") is None
