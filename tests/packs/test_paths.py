"""CAP-0171 WI-01 carried obligation 2: ``is_safe_relative`` rejects Windows-unsafe paths.

Besides traversal, drives, backslashes and empty segments (WI-01), a listed path must not
hold NUL or another control character, a Windows reserved device name in any segment
(with or without extension, any case), or a segment ending in a dot or a space.
"""

from __future__ import annotations

import json

import pytest
from _pack_fixtures import load_catalog, mt_entry

from lianiq.packs.catalog import is_safe_relative
from lianiq.packs.errors import PackCatalogError, PackFileError
from lianiq.packs.pack_file import UNSAFE_PATH, parse_pack_file

SAFE = [
    "model.bin",
    "sub/dir/model.bin",
    "de_DE-thorsten-medium.onnx.json",
    ".gitattributes",
    "console.txt",  # a reserved name only as a whole segment stem
    "COM10",
    "COM",
    "CONIN",
    "LPT¹0",
    "auxiliary/file",
    "a.b.c",
    "name with space.txt",
]
CONTROL = ["a\x00b", "nul\x00", "tab\there", "line\nbreak", "cr\r", "esc\x1b", "del\x7f", "\x01"]
RESERVED = [
    "CON",
    "con",
    "Con.txt",
    "PRN",
    "AUX.json",
    "NUL",
    "nul.tar.gz",
    "COM1",
    "com9.log",
    "LPT1",
    "lpt9.bin",
    "sub/CON",
    "aux/model.bin",
    "dir/NUL.txt/x",
    "CON .txt",  # Windows ignores trailing spaces of the stem
    "COM0",
    "lpt0.txt",
    "COM¹",
    "com².log",
    "LPT³",
    "sub/lpt¹.bin",
    "CONIN$",
    "conout$.txt",
    "dir/CONOUT$",
]
TRAILING = ["name.", "name ", "dir./file", "dir /file", "a/b.", "...", "a/ "]
WI01 = ["", "/abs", "../up", "a/../b", "./a", "a//b", "a/", "C:/x", "c:x", "sub\\x"]


@pytest.mark.parametrize("path", SAFE)
def test_ordinary_names_stay_safe(path: str) -> None:
    assert is_safe_relative(path)


@pytest.mark.parametrize("path", CONTROL)
def test_nul_and_control_characters_are_unsafe(path: str) -> None:
    assert not is_safe_relative(path)


@pytest.mark.parametrize("path", RESERVED)
def test_reserved_device_names_in_any_segment_are_unsafe(path: str) -> None:
    assert not is_safe_relative(path)


@pytest.mark.parametrize("path", TRAILING)
def test_segments_ending_in_a_dot_or_space_are_unsafe(path: str) -> None:
    assert not is_safe_relative(path)


@pytest.mark.parametrize("path", WI01)
def test_the_wi01_rules_still_hold(path: str) -> None:
    assert not is_safe_relative(path)


@pytest.mark.parametrize("path", [None, 3, b"model.bin"])
def test_non_strings_are_unsafe(path: object) -> None:
    assert not is_safe_relative(path)


@pytest.mark.parametrize("path", ["CON", "a\x00b", "model.bin."])
def test_the_catalog_refuses_such_a_listed_path(tmp_path, path: str) -> None:
    entry = mt_entry()
    entry["files"][0]["path"] = path
    with pytest.raises(PackCatalogError, match="unsafe path"):
        load_catalog(tmp_path, entry)


@pytest.mark.parametrize("root", ["models/CON", "models/x.", "models/a\x07"])
def test_the_catalog_refuses_such_a_root(tmp_path, root: str) -> None:
    entry = mt_entry()
    entry["root"] = root
    with pytest.raises(PackCatalogError, match="root"):
        load_catalog(tmp_path, entry)


@pytest.mark.parametrize("path", ["LPT3.bin", "x\x00", "dir /a"])
def test_a_pack_file_naming_such_a_path_is_rejected_by_name(path: str) -> None:
    document = {"format": "lianiq-pack/v1", "id": "mt-a", "version": "1"}
    document["files"] = [{"path": path, "size": 1, "sha256": "0" * 64}]
    raw = json.dumps(document)
    with pytest.raises(PackFileError) as caught:
        parse_pack_file(raw.encode("utf-8"))
    assert caught.value.reason == UNSAFE_PATH.format(path=path)
