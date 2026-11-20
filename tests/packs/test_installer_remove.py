"""CAP-0171 AC-15 (Integration half): ``PackInstaller.remove`` is journaled like a swap.

Removal deletes the listed files, the pack file and the records; the root and its empty
parents go when left empty, a root with unlisted files stays; a failure changes nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _install_fixtures import (
    MANIFEST,
    MT_V1,
    Fault,
    archive_pack_entry,
    archive_tar,
    catalog_of,
    download,
    installer,
    models_scratch,
    mt_pack_entry,
    state,
    tree,
)
from _pack_fixtures import capability_catalog

from lianiq.languages import DirectedEdge, ReadinessStatus
from lianiq.packs.errors import InstallFailed
from lianiq.packs.manifest import Manifest
from lianiq.packs.state import PackState

ROOT = "models/opus-mt-de-zh"


@pytest.fixture
def v1(tmp_path: Path):
    return catalog_of(tmp_path / "c1", mt_pack_entry())


def translation_status(project: Path, packs) -> ReadinessStatus:
    manifest = Manifest.read(project / MANIFEST)
    catalog = capability_catalog(project, packs, manifest)
    return catalog.translation(DirectedEdge.from_key("de>zh-Hans")).status


def test_ac15_remove_deletes_files_records_and_the_empty_root(tmp_path, v1) -> None:
    project = tmp_path / "p"
    download(project, v1, MT_V1)
    (project / "models" / "keep.txt").write_bytes(b"other models stay")
    assert translation_status(project, v1) is ReadinessStatus.VALIDATED

    installer(project, v1).remove(v1.get("mt-a"))

    assert not (project / ROOT).exists()
    manifest = Manifest.read(project / MANIFEST)
    assert manifest.pack("mt-a") is None
    assert not [a for a in manifest.artifacts if str(a.get("path", "")).startswith(ROOT)]
    assert (project / "models" / "keep.txt").exists()
    assert translation_status(project, v1) is ReadinessStatus.MISSING
    assert state(project, v1).state is PackState.DOWNLOADABLE
    assert models_scratch(project) == []


def test_ac15_a_root_with_unlisted_files_stays(tmp_path, v1) -> None:
    project = tmp_path / "p"
    download(project, v1, MT_V1)
    (project / ROOT / "notes.txt").write_bytes(b"mine")

    installer(project, v1).remove(v1.get("mt-a"))

    assert tree(project / ROOT) == {"notes.txt": b"mine"}
    assert state(project, v1).state is PackState.DOWNLOADABLE


def test_remove_deletes_empty_parents_up_to_models(tmp_path) -> None:
    project = tmp_path / "p"
    payload = archive_tar()
    packs = catalog_of(tmp_path / "c", archive_pack_entry(payload))
    from _install_fixtures import ARCHIVE_URL, FakeTransport

    download(project, packs, {}, transport=FakeTransport({ARCHIVE_URL: payload}), pack_id="tts-z")
    pack = packs.get("tts-z")
    assert (project / pack.root).is_dir()

    installer(project, packs).remove(pack)

    assert not (project / "models" / "sherpa").exists()
    assert (project / "models").is_dir()


def test_remove_of_an_older_script_install_drops_its_records(tmp_path, v1) -> None:
    from _pack_fixtures import script_install

    project = tmp_path / "p"
    script_install(project, v1.get("mt-a"), MT_V1)

    installer(project, v1).remove(v1.get("mt-a"))

    assert not (project / ROOT).exists()
    assert Manifest.read(project / MANIFEST).artifacts == ()


@pytest.mark.parametrize("at", [1, 2, 4])
def test_a_failed_move_during_remove_changes_nothing(tmp_path, v1, monkeypatch, at) -> None:
    project = tmp_path / "p"
    download(project, v1, MT_V1)
    before, manifest = tree(project / ROOT), (project / MANIFEST).read_bytes()
    Fault(monkeypatch, at, PermissionError(32, "sharing violation"))

    with pytest.raises(InstallFailed):
        installer(project, v1).remove(v1.get("mt-a"))

    assert tree(project / ROOT) == before
    assert (project / MANIFEST).read_bytes() == manifest
    assert state(project, v1).state is PackState.VALIDATED
    assert models_scratch(project) == []


def test_a_failed_manifest_write_during_remove_changes_nothing(tmp_path, v1, monkeypatch) -> None:
    project = tmp_path / "p"
    download(project, v1, MT_V1)
    before, manifest = tree(project / ROOT), (project / MANIFEST).read_bytes()

    def broken(self, path):
        raise OSError("disk full")

    monkeypatch.setattr(Manifest, "write", broken)
    with pytest.raises(InstallFailed):
        installer(project, v1).remove(v1.get("mt-a"))
    monkeypatch.undo()

    assert tree(project / ROOT) == before
    assert (project / MANIFEST).read_bytes() == manifest
    assert models_scratch(project) == []


def test_a_crash_during_remove_is_recovered(tmp_path, v1, monkeypatch) -> None:
    class Crash(BaseException):
        pass

    project = tmp_path / "p"
    download(project, v1, MT_V1)
    before, manifest = tree(project / ROOT), (project / MANIFEST).read_bytes()
    Fault(monkeypatch, 3, Crash())
    with pytest.raises(Crash):
        installer(project, v1).remove(v1.get("mt-a"))
    monkeypatch.undo()

    assert installer(project, v1).recover() == ("mt-a",)
    assert tree(project / ROOT) == before
    assert (project / MANIFEST).read_bytes() == manifest
    assert models_scratch(project) == []


def test_a_pack_id_that_is_not_one_folder_name_is_refused(tmp_path, v1) -> None:
    from dataclasses import replace

    project = tmp_path / "p"
    download(project, v1, MT_V1)
    unsafe = replace(v1.get("mt-a"), id="../escape")
    with pytest.raises(InstallFailed, match="pack id"):
        installer(project, v1).remove(unsafe)
    assert state(project, v1).state is PackState.VALIDATED
