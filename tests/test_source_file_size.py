"""Every Python source file fits the inline-publish limit (CAP-0168, lianiq#96).

The walk covers every ``*.py`` file under ``lianiq/``, ``tests/``, ``scripts/`` and the
CAP-0174 native test tooling in ``native_e2e/`` and ``tools/native-e2e/`` (spec §6.1); a
root that does not exist yet is skipped, and so is ``__pycache__``. The 32 KiB AC-01 check
for ``lianiq/ui/`` stays in ``test_ui_module_sizes.py``.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = ("lianiq", "tests", "scripts", "native_e2e", "tools/native-e2e")
# The Factory SCM Gateway publishes file content inline in one request, so every Python
# source file must stay at or below 12 KiB (12,288 bytes) to be publishable through it.
MAX_SOURCE_FILE_BYTES = 12_288


def source_files(root: Path = ROOT) -> list[Path]:
    return [
        path
        for folder in SOURCE_ROOTS
        if (root / folder).is_dir()
        for path in sorted((root / folder).rglob("*.py"))
        if path.is_file() and "__pycache__" not in path.relative_to(root).parts
    ]


def oversized(files: list[Path], root: Path = ROOT) -> list[str]:
    return [
        f"{path.relative_to(root).as_posix()}: {path.stat().st_size} bytes"
        for path in files
        if path.stat().st_size > MAX_SOURCE_FILE_BYTES
    ]


def test_every_python_source_file_is_at_most_12_kib() -> None:
    files = source_files()
    assert ROOT / "lianiq" / "pipeline.py" in files  # the walk sees each root
    assert ROOT / "tests" / "test_source_file_size.py" in files
    assert ROOT / "scripts" / "doctor.py" in files
    assert ROOT / "native_e2e" / "ssim.py" in files
    assert oversized(files) == []


def test_the_walk_reports_each_offender_with_its_size(tmp_path: Path) -> None:
    for folder in SOURCE_ROOTS[:-1]:  # tools/native-e2e is absent: the walk skips it
        (tmp_path / folder / "__pycache__").mkdir(parents=True)
    (tmp_path / "lianiq" / "at_limit.py").write_bytes(b"#" * MAX_SOURCE_FILE_BYTES)
    (tmp_path / "tests" / "over.py").write_bytes(b"#" * (MAX_SOURCE_FILE_BYTES + 1))
    (tmp_path / "scripts" / "notes.txt").write_bytes(b"#" * (MAX_SOURCE_FILE_BYTES + 1))
    (tmp_path / "scripts" / "__pycache__" / "cached.py").write_bytes(b"#" * 20_000)
    (tmp_path / "native_e2e" / "evidence").mkdir()
    (tmp_path / "native_e2e" / "evidence" / "big.py").write_bytes(b"#" * 20_000)

    files = source_files(tmp_path)

    assert [path.relative_to(tmp_path).as_posix() for path in files] == [
        "lianiq/at_limit.py",
        "tests/over.py",
        "native_e2e/evidence/big.py",
    ]
    assert oversized(files, tmp_path) == [
        "tests/over.py: 12289 bytes",
        "native_e2e/evidence/big.py: 20000 bytes",
    ]


def test_the_walk_covers_the_native_tools_folder(tmp_path: Path) -> None:
    (tmp_path / "tools" / "native-e2e" / "host").mkdir(parents=True)
    (tmp_path / "tools" / "native-e2e" / "host" / "egress-proxy.py").write_bytes(b"#" * 12_289)

    assert oversized(source_files(tmp_path), tmp_path) == [
        "tools/native-e2e/host/egress-proxy.py: 12289 bytes"
    ]
