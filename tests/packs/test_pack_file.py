"""CAP-0171 contract.md §2: ``lianiq-pack.json`` parse, render and check (AC-11 Unit half)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from _pack_fixtures import load_catalog, mt_entry, sha

from lianiq.packs.catalog import PackDefinition, PackFile
from lianiq.packs.errors import PackFileError
from lianiq.packs.pack_file import (
    PACK_FILE_NAME,
    PACK_FORMAT,
    PackFileDocument,
    check_against,
    parse_pack_file,
    render_pack_file,
)


@pytest.fixture
def pack(tmp_path: Path) -> PackDefinition:
    return load_catalog(tmp_path, mt_entry()).get("mt-a")


def _raw(**changes: Any) -> bytes:
    document: dict[str, Any] = {
        "format": PACK_FORMAT,
        "id": "mt-a",
        "version": "1",
        "files": [{"path": "a.bin", "size": 2, "sha256": sha(b"ab")}],
    }
    document.update(changes)
    return json.dumps(document).encode("utf-8")


def _reason(error: pytest.ExceptionInfo[PackFileError]) -> str:
    return error.value.reason


def test_constants() -> None:
    assert PACK_FILE_NAME == "lianiq-pack.json"
    assert PACK_FORMAT == "lianiq-pack/v1"


def test_render_is_sorted_utf8_json_with_a_trailing_newline(pack: PackDefinition) -> None:
    raw = render_pack_file(pack)

    assert raw.endswith(b"\n")
    payload = json.loads(raw.decode("utf-8"))
    assert list(payload) == sorted(payload)
    assert payload["format"] == PACK_FORMAT
    assert payload["id"] == "mt-a"
    assert payload["version"] == "1"
    assert [item["path"] for item in payload["files"]] == ["pytorch_model.bin", "config.json"]
    assert all(sorted(item) == ["path", "sha256", "size"] for item in payload["files"])
    assert render_pack_file(pack) == raw  # deterministic


def test_parse_of_a_render_round_trips_and_checks(pack: PackDefinition) -> None:
    document = parse_pack_file(render_pack_file(pack))

    assert document == PackFileDocument(
        "mt-a", "1", tuple(PackFile(f.path, f.size, f.sha256, None) for f in pack.files)
    )
    check_against(document, pack)  # no error


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"not json",
        b"\xff\xfe",
        b"[]",
        _raw(format="lianiq-pack/v2"),
        _raw(id=""),
        _raw(version=3),
        _raw(files={}),
        _raw(files=[{"path": "a.bin", "size": "2", "sha256": "0" * 64}]),
        _raw(files=[{"path": "a.bin", "size": True, "sha256": "0" * 64}]),
        _raw(files=[{"path": "a.bin", "size": 2, "sha256": "xyz"}]),
        _raw(files=[{"path": "a.bin", "size": 2}]),
        _raw(files=[{"path": "a.bin", "size": 2, "sha256": "0" * 64}] * 2),
    ],
)
def test_a_malformed_pack_file_is_no_pack_file(raw: bytes) -> None:
    with pytest.raises(PackFileError) as raised:
        parse_pack_file(raw)
    assert _reason(raised) == "no pack file"


@pytest.mark.parametrize("path", ["../a.bin", "/a.bin", "C:/a.bin", "a\\b.bin", "a/./b", "a//b"])
def test_an_unsafe_listed_path_is_rejected(path: str) -> None:
    raw = _raw(files=[{"path": path, "size": 1, "sha256": "0" * 64}])
    with pytest.raises(PackFileError) as raised:
        parse_pack_file(raw)
    assert _reason(raised) == f"unsafe path {path}"


def _document(pack: PackDefinition, **changes: Any) -> PackFileDocument:
    files = tuple(PackFile(f.path, f.size, f.sha256, None) for f in pack.files)
    values: dict[str, Any] = {"id": pack.id, "version": pack.version, "files": files}
    values.update(changes)
    return PackFileDocument(**values)


def test_check_against_rejects_each_mismatch_with_its_reason(pack: PackDefinition) -> None:
    weights, config = (PackFile(f.path, f.size, f.sha256, None) for f in pack.files)
    cases = {
        "unknown pack mt-b": _document(pack, id="mt-b"),
        "version 2 is not offered": _document(pack, version="2"),
        "file config.json is missing": _document(pack, files=(weights,)),
        "file pytorch_model.bin has the wrong size": _document(
            pack, files=(PackFile(weights.path, weights.size + 1, weights.sha256, None), config)
        ),
        "file pytorch_model.bin failed the integrity check": _document(
            pack, files=(PackFile(weights.path, weights.size, "0" * 64, None), config)
        ),
        "version 1 is not offered": _document(
            pack, files=(weights, config, PackFile("extra.bin", 1, "0" * 64, None))
        ),
    }
    for reason, document in cases.items():
        with pytest.raises(PackFileError) as raised:
            check_against(document, pack)
        assert _reason(raised) == reason
    # The order of listed files does not matter.
    check_against(_document(pack, files=(config, weights)), pack)


def test_pack_file_error_carries_every_contract_reason() -> None:
    reasons = [
        "no pack file",
        "unknown pack x",
        "version 2 is not offered",
        "file a is missing",
        "file a has the wrong size",
        "file a failed the integrity check",
        "unsafe path ../a",
        "the archive cannot be read",
    ]
    for reason in reasons:
        error = PackFileError(reason)
        assert error.reason == reason
        assert str(error) == reason
