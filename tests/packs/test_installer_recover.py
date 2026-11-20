"""CAP-0171 AC-25 (Integration): ``PackInstaller.recover()`` after a crash at launch.

A crash is simulated by a ``BaseException`` from a file move, which the installer does not
catch, so the swap journal, staging and ``.lianiq-previous`` stay as a killed process leaves
them. A fresh installer then recovers them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _install_fixtures import (
    MANIFEST,
    MT_V1,
    MT_V2,
    Fault,
    catalog_of,
    download,
    installer,
    models_scratch,
    mt_pack_entry,
    state,
    tree,
)

from lianiq.packs import journal as journal_module
from lianiq.packs.manifest import Manifest
from lianiq.packs.pack_file import PACK_FILE_NAME
from lianiq.packs.state import PackState

ROOT = "models/opus-mt-de-zh"


class Crash(BaseException):
    """The process dies here."""


@pytest.fixture
def v1(tmp_path: Path):
    return catalog_of(tmp_path / "c1", mt_pack_entry())


@pytest.fixture
def v2(tmp_path: Path):
    return catalog_of(tmp_path / "c2", mt_pack_entry(version="2", files=MT_V2))


def crash_at(monkeypatch, at: int) -> None:
    Fault(monkeypatch, at, Crash())


def journals(project: Path) -> list[dict]:
    staging = project / "models" / ".lianiq-staging"
    return [json.loads(p.read_text("utf-8")) for p in sorted(staging.glob("*/journal.json"))]


@pytest.mark.parametrize("at", [1, 3, 4, 5, 6, 8])
def test_ac25_a_crash_during_an_update_swap_restores_version_one(
    tmp_path, v1, v2, monkeypatch, at
) -> None:
    project = tmp_path / "p"
    download(project, v1, MT_V1)
    before, manifest = tree(project / ROOT), (project / MANIFEST).read_bytes()
    crash_at(monkeypatch, at)
    with pytest.raises(Crash):
        download(project, v2, MT_V2)
    monkeypatch.undo()
    assert journals(project), "the crash left a journal"

    assert installer(project, v2).recover() == ("mt-a",)

    assert tree(project / ROOT) == before
    assert (project / MANIFEST).read_bytes() == manifest
    assert state(project, v2).state is PackState.VALIDATED
    assert models_scratch(project) == []


@pytest.mark.parametrize("at", [1, 2, 4])
def test_ac25_a_crash_during_a_first_install_deletes_the_moved_in_files(
    tmp_path, v1, monkeypatch, at
) -> None:
    project = tmp_path / "p"
    crash_at(monkeypatch, at)
    with pytest.raises(Crash):
        download(project, v1, MT_V1)
    monkeypatch.undo()
    assert journals(project)[0]["pack_id"] == "mt-a"

    assert installer(project, v1).recover() == ("mt-a",)

    assert not (project / ROOT).exists()
    assert Manifest.read(project / MANIFEST).pack("mt-a") is None
    status = state(project, v1)
    assert status.state is PackState.DOWNLOADABLE
    manifest = Manifest.read(project / MANIFEST)
    from _pack_fixtures import capability_catalog

    from lianiq.languages import DirectedEdge, ReadinessStatus

    capabilities = capability_catalog(project, v1, manifest)
    edge = DirectedEdge.from_key("de>zh-Hans")
    assert capabilities.translation(edge).status is ReadinessStatus.MISSING
    assert models_scratch(project) == []


def test_ac25_a_crash_after_the_manifest_write_restores_the_manifest(
    tmp_path, v1, v2, monkeypatch
) -> None:
    project = tmp_path / "p"
    download(project, v1, MT_V1)
    before, manifest = tree(project / ROOT), (project / MANIFEST).read_bytes()
    original = journal_module.Journal.append

    def dying(self, op: str, path: str | None = None) -> None:
        if op == "commit":
            raise Crash()
        original(self, op, path)

    monkeypatch.setattr(journal_module.Journal, "append", dying)
    with pytest.raises(Crash):
        download(project, v2, MT_V2)
    monkeypatch.undo()
    assert Manifest.read(project / MANIFEST).pack("mt-a").version == "2"

    installer(project, v2).recover()

    assert tree(project / ROOT) == before
    assert (project / MANIFEST).read_bytes() == manifest
    assert state(project, v2).state is PackState.VALIDATED


def test_a_committed_job_is_only_cleaned_up(tmp_path, v1, v2, monkeypatch) -> None:
    project = tmp_path / "p"
    download(project, v1, MT_V1)
    from lianiq.packs import installer as installer_module

    monkeypatch.setattr(installer_module, "delete_tree", lambda path: None)
    download(project, v2, MT_V2)
    monkeypatch.undo()
    assert models_scratch(project) == [".lianiq-previous", ".lianiq-staging"]
    after = tree(project / ROOT)

    assert installer(project, v2).recover() == ("mt-a",)

    assert tree(project / ROOT) == after
    assert state(project, v2).state is PackState.VALIDATED
    assert models_scratch(project) == []


def test_a_staging_folder_without_a_journal_is_deleted(tmp_path, v1) -> None:
    project = tmp_path / "p"
    leftover = project / "models" / ".lianiq-staging" / "abc" / "pack"
    leftover.mkdir(parents=True)
    (leftover / "pytorch_model.bin").write_bytes(b"partial")

    assert installer(project, v1).recover() == ()
    assert models_scratch(project) == []


def test_a_previous_folder_without_journal_is_moved_back_on_mismatch(tmp_path, v1) -> None:
    project = tmp_path / "p"
    download(project, v1, MT_V1)
    before = tree(project / ROOT)
    previous = project / "models" / ".lianiq-previous" / "mt-a"
    previous.mkdir(parents=True)
    for name in ("config.json", PACK_FILE_NAME):
        (project / ROOT / name).replace(previous / name)
    (previous / "unlisted.bin").write_bytes(b"never moved back")

    assert installer(project, v1).recover() == ("mt-a",)

    assert tree(project / ROOT) == before
    assert models_scratch(project) == []


def test_a_previous_folder_without_journal_is_deleted_on_match(tmp_path, v1) -> None:
    project = tmp_path / "p"
    download(project, v1, MT_V1)
    before = tree(project / ROOT)
    previous = project / "models" / ".lianiq-previous" / "mt-a"
    previous.mkdir(parents=True)
    (previous / "config.json").write_bytes(b"an older copy")

    assert installer(project, v1).recover() == ("mt-a",)

    assert tree(project / ROOT) == before
    assert models_scratch(project) == []


def test_recover_undoes_only_catalog_paths(tmp_path, v1) -> None:
    """Carried obligation 1: a journal naming another path never moves or deletes it."""
    project = tmp_path / "p"
    victim = project / "models" / "other" / "keep.bin"
    victim.parent.mkdir(parents=True)
    victim.write_bytes(b"keep")
    job = project / "models" / ".lianiq-staging" / "j1"
    job.mkdir(parents=True)
    entries = [{"op": "in", "path": "../other/keep.bin"}, {"op": "in", "path": "CON"}]
    payload = {
        "format": "lianiq-swap-journal/v1",
        "pack_id": "mt-a",
        "version": "1",
        "operation": "install",
        "entries": entries,
    }
    (job / "journal.json").write_text(json.dumps(payload), "utf-8")

    installer(project, v1).recover()

    assert victim.read_bytes() == b"keep"
    assert models_scratch(project) == []


def test_a_journal_of_an_unknown_pack_touches_no_pack_root(tmp_path, v1) -> None:
    project = tmp_path / "p"
    download(project, v1, MT_V1)
    before = tree(project / ROOT)
    job = project / "models" / ".lianiq-staging" / "j2"
    job.mkdir(parents=True)
    payload = {
        "format": "lianiq-swap-journal/v1",
        "pack_id": "gone",
        "version": "1",
        "operation": "install",
        "entries": [{"op": "in", "path": "config.json"}],
    }
    (job / "journal.json").write_text(json.dumps(payload), "utf-8")

    installer(project, v1).recover()

    assert tree(project / ROOT) == before
    assert models_scratch(project) == []
