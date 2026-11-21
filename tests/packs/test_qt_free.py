"""CAP-0171 contract preamble: the pack core is Qt-free (the ``lianiq.meeting`` precedent)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

QT_FREE_MODULES = (
    "lianiq.packs",
    "lianiq.packs.catalog",
    "lianiq.packs.disk",
    "lianiq.packs.errors",
    "lianiq.packs.import_source",
    "lianiq.packs.installer",
    "lianiq.packs.jobs",
    "lianiq.packs.journal",
    "lianiq.packs.manifest",
    "lianiq.packs.pack_file",
    "lianiq.packs.paths",
    "lianiq.packs.protection",
    "lianiq.packs.recovery",
    "lianiq.packs.sources",
    "lianiq.packs.state",
    "lianiq.packs.transfer",
    "lianiq.packs.verify",
    "lianiq.languages.pack_readiness",
)


def test_pack_core_imports_no_pyside6() -> None:
    imports = "; ".join(f"import {module}" for module in QT_FREE_MODULES)
    script = f"import sys; {imports}; print(any(m.startswith('PySide6') for m in sys.modules))"
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        check=True,
        cwd=Path(__file__).resolve().parents[2],
        text=True,
    )
    assert result.stdout.strip() == "False"


def test_pack_sources_name_no_pyside6() -> None:
    root = Path(__file__).resolve().parents[2] / "lianiq"
    sources = [*sorted((root / "packs").glob("*.py")), root / "languages/pack_readiness.py"]
    assert len(sources) == 18
    for source in sources:
        assert "PySide6" not in source.read_text(encoding="utf-8"), source.name


def test_job_values_for_state() -> None:
    from lianiq.packs.jobs import JobPhase, JobView

    assert [phase.value for phase in JobPhase] == ["transfer", "check", "swap"]
    view = JobView("mt-a", "update", JobPhase.SWAP, 3, 9)
    assert (view.pack_id, view.operation, view.phase, view.done, view.total) == (
        "mt-a",
        "update",
        JobPhase.SWAP,
        3,
        9,
    )
    with pytest.raises(AttributeError):  # frozen
        view.done = 4  # type: ignore[misc]


def test_pack_sources_use_only_the_standard_library_for_transfers() -> None:
    """Spec §8: runtime ``lianiq/`` keeps no ``huggingface_hub`` import; ``urllib`` only."""
    root = Path(__file__).resolve().parents[2] / "lianiq"
    for source in sorted((root / "packs").glob("*.py")):
        text = source.read_text(encoding="utf-8")
        assert "huggingface_hub" not in text and "import requests" not in text, source.name
