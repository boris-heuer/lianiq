"""CAP-0171 contract.md §2/§5: ``ImportSource`` from a folder or a ``.zip`` (AC-10, AC-11).

Only the catalog entry's listed files are copied, under their catalog paths; unlisted files
are ignored; every rejection carries its contract.md §2 reason. No network is used.
"""

from __future__ import annotations

import json
import os
import stat
import zipfile
from pathlib import Path

import pytest
from _install_fixtures import (
    MT_V1,
    Progress,
    catalog_of,
    mt_pack_entry,
    pack_folder,
    pack_zip,
    tree,
)

from lianiq.packs.errors import PackFileError
from lianiq.packs.jobs import CancelToken, JobPhase
from lianiq.packs.pack_file import (
    ARCHIVE_UNREADABLE,
    FILE_ALTERED,
    FILE_MISSING,
    FILE_WRONG_SIZE,
    NO_PACK_FILE,
    PACK_FILE_NAME,
    UNKNOWN_PACK,
    UNSAFE_PATH,
    VERSION_NOT_OFFERED,
)
from lianiq.packs.sources import ImportSource


@pytest.fixture
def mt(tmp_path: Path):
    return catalog_of(tmp_path / "c", mt_pack_entry()).get("mt-a")


def run(source: Path, pack, staging: Path) -> Progress:
    staging.mkdir(parents=True, exist_ok=True)
    progress = Progress()
    ImportSource(source).fetch(pack, staging, progress, CancelToken())
    return progress


def reason(source: Path, pack, staging: Path) -> str:
    with pytest.raises(PackFileError) as caught:
        run(source, pack, staging)
    return caught.value.reason


def test_a_folder_import_copies_only_the_listed_files(tmp_path, mt, network_attempts) -> None:
    source = pack_folder(tmp_path / "src", mt, MT_V1)
    progress = run(source, mt, tmp_path / "s")

    assert tree(tmp_path / "s") == MT_V1  # no extra file, no pack file (the installer writes it)
    assert progress.phases() == [JobPhase.TRANSFER]
    assert progress.calls[-1] == (JobPhase.TRANSFER, mt.installed_bytes, mt.installed_bytes)
    assert network_attempts == []


def test_a_zip_import_copies_only_the_listed_files(tmp_path, mt, network_attempts) -> None:
    source = pack_zip(tmp_path / "pack.zip", mt, MT_V1)
    run(source, mt, tmp_path / "s")

    assert tree(tmp_path / "s") == MT_V1
    assert network_attempts == []


def test_no_pack_file_in_a_folder_or_zip(tmp_path, mt) -> None:
    folder = pack_folder(tmp_path / "src", mt, MT_V1)
    (folder / PACK_FILE_NAME).unlink()
    assert reason(folder, mt, tmp_path / "s1") == NO_PACK_FILE
    assert reason(pack_zip(tmp_path / "p.zip", None, MT_V1), mt, tmp_path / "s2") == NO_PACK_FILE
    assert reason(tmp_path / "absent", mt, tmp_path / "s3") == NO_PACK_FILE


def test_a_malformed_pack_file_is_no_pack_file(tmp_path, mt) -> None:
    folder = pack_folder(tmp_path / "src", mt, MT_V1)
    (folder / PACK_FILE_NAME).write_bytes(b"{not json")
    assert reason(folder, mt, tmp_path / "s") == NO_PACK_FILE


def test_an_unknown_pack_or_version(tmp_path, mt) -> None:
    other = catalog_of(tmp_path / "o", {**mt_pack_entry(), "id": "mt-b"}).get("mt-b")
    assert reason(pack_folder(tmp_path / "a", other, MT_V1), mt, tmp_path / "s1") == (
        UNKNOWN_PACK.format(id="mt-b")
    )
    newer = catalog_of(tmp_path / "n", mt_pack_entry(version="2")).get("mt-a")
    assert reason(pack_folder(tmp_path / "b", newer, MT_V1), mt, tmp_path / "s2") == (
        VERSION_NOT_OFFERED.format(version="2")
    )


def test_a_missing_listed_file(tmp_path, mt) -> None:
    folder = pack_folder(tmp_path / "src", mt, MT_V1)
    (folder / "sub" / "vocab.json").unlink()
    assert reason(folder, mt, tmp_path / "s") == FILE_MISSING.format(path="sub/vocab.json")
    partial = {k: v for k, v in MT_V1.items() if k != "config.json"}
    zipped = pack_zip(tmp_path / "p.zip", mt, partial)
    assert reason(zipped, mt, tmp_path / "s2") == FILE_MISSING.format(path="config.json")


def test_a_file_of_the_wrong_size_or_digest(tmp_path, mt) -> None:
    folder = pack_folder(tmp_path / "a", mt, {**MT_V1, "config.json": b'{"v": 10}'})
    assert reason(folder, mt, tmp_path / "s1") == FILE_WRONG_SIZE.format(path="config.json")
    folder = pack_folder(tmp_path / "b", mt, {**MT_V1, "config.json": b'{"v": 9}'})
    assert reason(folder, mt, tmp_path / "s2") == FILE_ALTERED.format(path="config.json")
    zipped = pack_zip(tmp_path / "p.zip", mt, {**MT_V1, "config.json": b'{"v": 9}'})
    assert reason(zipped, mt, tmp_path / "s3") == FILE_ALTERED.format(path="config.json")


def test_a_pack_file_with_a_traversal_path(tmp_path, mt) -> None:
    folder = pack_folder(tmp_path / "src", mt, MT_V1)
    document = json.loads((folder / PACK_FILE_NAME).read_text("utf-8"))
    document["files"][0]["path"] = "../outside.bin"
    (folder / PACK_FILE_NAME).write_text(json.dumps(document), "utf-8")
    assert reason(folder, mt, tmp_path / "s") == UNSAFE_PATH.format(path="../outside.bin")
    assert not (tmp_path / "outside.bin").exists()


@pytest.mark.parametrize("name", ["../escape.bin", "/abs.bin", "dir/../../x", "C:/x.bin"])
def test_a_zip_with_an_unsafe_member_name(tmp_path, mt, name) -> None:
    zipped = pack_zip(tmp_path / "p.zip", mt, MT_V1, extra={name: b"x"})
    assert reason(zipped, mt, tmp_path / "s") == UNSAFE_PATH.format(path=name)
    assert tree(tmp_path / "s") == {}


def test_a_zip_with_a_linked_listed_member(tmp_path, mt) -> None:
    path = tmp_path / "p.zip"
    with zipfile.ZipFile(path, "w") as bundle:
        from lianiq.packs.pack_file import render_pack_file

        bundle.writestr(PACK_FILE_NAME, render_pack_file(mt))
        for name, data in MT_V1.items():
            info = zipfile.ZipInfo(name)
            if name == "config.json":
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            bundle.writestr(info, data)
    assert reason(path, mt, tmp_path / "s") == UNSAFE_PATH.format(path="config.json")


@pytest.mark.skipif(os.name != "nt" and os.geteuid() == 0, reason="needs an unprivileged link")
def test_a_folder_with_a_linked_listed_file(tmp_path, mt) -> None:
    folder = pack_folder(tmp_path / "src", mt, MT_V1)
    outside = tmp_path / "outside.json"
    outside.write_bytes(MT_V1["config.json"])
    (folder / "config.json").unlink()
    try:
        (folder / "config.json").symlink_to(outside)
    except OSError:
        pytest.skip("symbolic links are not permitted here")
    assert reason(folder, mt, tmp_path / "s") == UNSAFE_PATH.format(path="config.json")


@pytest.mark.parametrize("content", [b"PK\x03\x04 truncated", b"plain text, not a zip"])
def test_an_unreadable_archive(tmp_path, mt, content) -> None:
    path = tmp_path / "broken.zip"
    path.write_bytes(content)
    assert reason(path, mt, tmp_path / "s") == ARCHIVE_UNREADABLE


def test_a_corrupt_member_of_a_zip_is_unreadable(tmp_path, mt) -> None:
    path = pack_zip(tmp_path / "p.zip", mt, MT_V1)
    data = bytearray(path.read_bytes())
    offset = data.index(MT_V1["pytorch_model.bin"])
    data[offset] ^= 0xFF  # stored member: the CRC no longer matches
    path.write_bytes(bytes(data))
    assert reason(path, mt, tmp_path / "s") in {
        ARCHIVE_UNREADABLE,
        FILE_ALTERED.format(path="pytorch_model.bin"),
    }


def test_import_never_writes_a_member_name_outside_staging(tmp_path, mt) -> None:
    zipped = pack_zip(tmp_path / "p.zip", mt, MT_V1)
    run(zipped, mt, tmp_path / "s")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["c", "p.zip", "s"]


@pytest.mark.skipif(os.name != "nt", reason="directory junctions are a Windows feature")
def test_a_folder_with_a_junction_in_a_listed_path(tmp_path, mt) -> None:
    import _winapi

    folder = pack_folder(tmp_path / "src", mt, MT_V1)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "vocab.json").write_bytes(MT_V1["sub/vocab.json"])
    (folder / "sub" / "vocab.json").unlink()
    (folder / "sub").rmdir()
    _winapi.CreateJunction(str(outside), str(folder / "sub"))
    assert reason(folder, mt, tmp_path / "s") == UNSAFE_PATH.format(path="sub/vocab.json")
