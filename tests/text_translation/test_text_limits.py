"""CAP-0172 contract §2: the 5,000 code point source rule (AC-11, AC-12 unit halves)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from lianiq.text_translation.limits import (
    MAX_SOURCE_CODE_POINTS,
    SourceCheck,
    check_source,
    source_length,
)

ROOT = Path(__file__).resolve().parents[2]
CORE_MODULES = ("limits", "state", "segments", "readiness", "jobs")


@pytest.mark.parametrize("text", ["", " ", "\n\n", "\t \u3000\n"])
def test_ac11_empty_or_whitespace_source_is_empty(text: str) -> None:
    assert check_source(text) is SourceCheck.EMPTY


@pytest.mark.parametrize(
    "unit",
    [
        "a",
        "汉",
        "e\u0301",  # e + combining acute: two code points
        "\U0001f44d\U0001f3fd",  # thumbs up with a skin-tone modifier: two code points
        "x\n",  # a pasted CRLF reaches the counter as one "\n"
    ],
)
def test_ac12_5000_code_points_pass_and_5001_are_too_long(unit: str) -> None:
    text = (unit * MAX_SOURCE_CODE_POINTS)[:MAX_SOURCE_CODE_POINTS]
    if not text.strip():
        text = "a" + text[1:]
    assert source_length(text) == 5_000
    assert check_source(text) is SourceCheck.OK
    assert check_source(text + "a") is SourceCheck.TOO_LONG


def test_every_code_point_counts() -> None:
    assert source_length("a b\nc") == 5
    assert source_length("e\u0301") == 2
    assert source_length("\U0001f44d\U0001f3fd") == 2
    assert source_length("汉字") == 2


def test_text_core_imports_no_pyside6() -> None:
    imports = "; ".join(f"import lianiq.text_translation.{name}" for name in CORE_MODULES)
    script = f"import sys; {imports}; print(any(m.startswith('PySide6') for m in sys.modules))"
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, check=True, cwd=ROOT, text=True
    )
    assert result.stdout.strip() == "False"
    for name in CORE_MODULES:
        source = ROOT / "lianiq" / "text_translation" / f"{name}.py"
        assert "PySide6" not in source.read_text(encoding="utf-8")
        assert "from lianiq.packs" not in source.read_text(encoding="utf-8")
