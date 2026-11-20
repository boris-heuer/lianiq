"""CAP-0171 contract.md §4: ``PackVerifier`` digests of listed files, cached by (path, size, mtime)."""

from __future__ import annotations

import os
from pathlib import Path

from _pack_fixtures import sha

from lianiq.packs.catalog import PackFile
from lianiq.packs.verify import FileReport, PackVerifier


def _listed(name: str, data: bytes) -> PackFile:
    return PackFile(name, len(data), sha(data), None)


def test_inspect_reports_missing_wrong_size_and_altered_files(tmp_path: Path) -> None:
    (tmp_path / "ok.bin").write_bytes(b"ok")
    (tmp_path / "big.bin").write_bytes(b"bigger")
    (tmp_path / "alt.bin").write_bytes(b"alt")
    files = [
        _listed("ok.bin", b"ok"),
        _listed("gone.bin", b"x"),
        _listed("big.bin", b"big"),
        _listed("alt.bin", b"ALT"),
    ]
    verifier = PackVerifier()

    report = verifier.inspect(tmp_path, files)

    assert report == FileReport(
        missing=("gone.bin",), wrong_size=("big.bin",), altered=("alt.bin",)
    )
    assert not report.ok
    assert verifier.inspect(tmp_path, files[:1]) == FileReport()
    assert verifier.inspect(tmp_path, files[:1]).ok
    # Without digests only presence and size count.
    assert verifier.inspect(tmp_path, files, digests=False).altered == ()


def test_a_manifest_record_overrides_the_listed_digest(tmp_path: Path) -> None:
    (tmp_path / "a.bin").write_bytes(b"aa")
    listed = [_listed("a.bin", b"aa")]
    verifier = PackVerifier()
    assert verifier.inspect(tmp_path, listed, {"a.bin": "0" * 64}).altered == ("a.bin",)
    assert verifier.inspect(tmp_path, listed, {"a.bin": sha(b"aa").upper()}).ok


def test_digests_are_cached_by_path_size_and_mtime(tmp_path: Path) -> None:
    hashed: list[str] = []

    def counting(path: Path) -> str:
        hashed.append(path.name)
        return sha(path.read_bytes())

    target = tmp_path / "a.bin"
    target.write_bytes(b"one")
    verifier = PackVerifier(counting)

    assert verifier.digest(target) == sha(b"one")
    assert verifier.digest(target) == sha(b"one")
    assert hashed == ["a.bin"]
    target.write_bytes(b"three")
    assert verifier.digest(target) == sha(b"three")
    assert hashed == ["a.bin", "a.bin"]
    verifier.invalidate()
    verifier.digest(target)
    assert hashed == ["a.bin", "a.bin", "a.bin"]


def test_a_same_size_rewrite_with_a_new_mtime_is_hashed_again(tmp_path: Path) -> None:
    target = tmp_path / "a.bin"
    target.write_bytes(b"one")
    os.utime(target, ns=(1_000_000_000, 1_000_000_000))
    verifier = PackVerifier()
    assert verifier.digest(target) == sha(b"one")

    target.write_bytes(b"two")
    os.utime(target, ns=(2_000_000_000, 2_000_000_000))

    assert verifier.digest(target) == sha(b"two")


def test_the_default_hash_is_sha256_in_blocks(tmp_path: Path) -> None:
    target = tmp_path / "large.bin"
    data = b"\x01" * (1024 * 1024 + 7)
    target.write_bytes(data)
    assert PackVerifier().digest(target) == sha(data)
