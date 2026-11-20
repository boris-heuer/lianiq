"""CAP-0171 contract.md §5 review findings B1, B2, C3: undo is idempotent and jobs are serial.

B1: a rollback that succeeded is marked ``undone`` before any clean-up, so a later
``recover()`` never undoes it a second time; undo never deletes a moved-in file whose
moved-out copy is gone. B2: a job of a pack whose staging still holds an unfinished journal
is refused, and undo restores only that pack's manifest records. C3: ``recover()`` contains
an error to its job, finishes the others and reports the failures.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from _install_fixtures import (
    MANIFEST,
    MT_V1,
    MT_V2,
    FakeTransport,
    Fault,
    catalog_of,
    download,
    installer,
    models_scratch,
    mt_pack_entry,
    payloads_for,
    state,
    tree,
)
from _pack_fixtures import VOICE_FILES, voice_entry

from lianiq.packs import installer as installer_module
from lianiq.packs import journal as journal_module
from lianiq.packs.errors import InstallFailed
from lianiq.packs.installer import NOT_RECOVERED
from lianiq.packs.journal import Journal, undo
from lianiq.packs.manifest import Manifest
from lianiq.packs.recovery import RecoveryFailed
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


@pytest.fixture
def both(tmp_path: Path):
    return catalog_of(tmp_path / "c3", mt_pack_entry(), voice_entry())


def keep_staging(monkeypatch) -> None:
    """``rmtree`` silently leaves every staging job (an antivirus lock, or a crash)."""
    real = installer_module.delete_tree

    def selective(path: Path) -> None:
        if path.parent.name != ".lianiq-staging":
            real(path)

    monkeypatch.setattr(installer_module, "delete_tree", selective)


def test_b1_a_rolled_back_update_is_not_undone_again(tmp_path, v1, v2, monkeypatch) -> None:
    project = tmp_path / "p"
    download(project, v1, MT_V1)
    before, manifest = tree(project / ROOT), (project / MANIFEST).read_bytes()
    keep_staging(monkeypatch)
    Fault(monkeypatch, 6, PermissionError(32, "sharing violation"))
    with pytest.raises(InstallFailed):
        download(project, v2, MT_V2)
    monkeypatch.undo()
    assert tree(project / ROOT) == before

    installer(project, v2).recover()

    assert tree(project / ROOT) == before
    assert (project / MANIFEST).read_bytes() == manifest
    assert state(project, v2).state is PackState.VALIDATED
    assert models_scratch(project) == []


def test_b1_a_rolled_back_first_install_is_not_undone_again(tmp_path, v1, monkeypatch) -> None:
    project = tmp_path / "p"
    keep_staging(monkeypatch)
    Fault(monkeypatch, 2, OSError(5, "I/O error"))
    with pytest.raises(InstallFailed):
        download(project, v1, MT_V1)
    monkeypatch.undo()
    jobs = list((project / "models" / ".lianiq-staging").iterdir())
    assert len(jobs) == 1 and Journal.read(jobs[0]).undone

    download(project, v1, MT_V1)  # an undone journal does not block the retry
    installer(project, v1).recover()

    assert state(project, v1).state is PackState.VALIDATED
    assert models_scratch(project) == []


def test_b1_undo_keeps_a_moved_in_path_whose_moved_out_copy_is_gone(tmp_path, v1) -> None:
    pack = v1.get("mt-a")
    base, previous, job = tmp_path / "root", tmp_path / "previous", tmp_path / "job"
    for folder in (base, previous, job):
        folder.mkdir()
    (base / "config.json").write_bytes(b"restored v1")
    journal = Journal.create(job, pack, "install")
    journal.append("out", "config.json")
    journal.append("in", "config.json")

    undo(journal, pack, base, previous)

    assert (base / "config.json").read_bytes() == b"restored v1"


def test_b2_an_unfinished_journal_blocks_install_and_remove(tmp_path, v1, monkeypatch) -> None:
    project = tmp_path / "p"
    Fault(monkeypatch, 2, OSError(5, "I/O error"))
    monkeypatch.setattr(installer_module, "undo", _failing_undo)
    with pytest.raises(InstallFailed):
        download(project, v1, MT_V1)
    monkeypatch.undo()

    for attempt in (lambda: download(project, v1, MT_V1), lambda: _remove(project, v1)):
        with pytest.raises(InstallFailed) as caught:
            attempt()
        assert caught.value.reason == NOT_RECOVERED

    installer(project, v1).recover()
    download(project, v1, MT_V1)
    assert state(project, v1).state is PackState.VALIDATED


def _failing_undo(*args, **kwargs) -> None:
    raise PermissionError(32, "the undo is blocked")


def _remove(project: Path, packs) -> None:
    installer(project, packs).remove(packs.get("mt-a"))


def test_b2_undo_restores_only_this_packs_manifest_records(tmp_path, both, monkeypatch) -> None:
    project = tmp_path / "p"
    download(project, both, MT_V1)
    original = journal_module.Journal.append

    def dying(self, op: str, path: str | None = None) -> None:
        if op == "commit":
            raise Crash()
        original(self, op, path)

    monkeypatch.setattr(journal_module.Journal, "append", dying)
    with pytest.raises(Crash):
        download(project, both, MT_V1)  # dies after its manifest write
    monkeypatch.undo()
    voice = FakeTransport(payloads_for(both.get("tts-a"), VOICE_FILES))
    download(project, both, VOICE_FILES, transport=voice, pack_id="tts-a")

    installer(project, both).recover()

    manifest = Manifest.read(project / MANIFEST)
    assert {record.id for record in manifest.packs} == {"mt-a", "tts-a"}
    assert state(project, both, "tts-a").state is PackState.VALIDATED
    assert state(project, both).state is PackState.VALIDATED


def test_c3_recover_contains_a_failing_job(tmp_path, both, monkeypatch, caplog) -> None:
    project = tmp_path / "p"
    download(project, both, MT_V1)
    voice = FakeTransport(payloads_for(both.get("tts-a"), VOICE_FILES))
    download(project, both, VOICE_FILES, transport=voice, pack_id="tts-a")
    expected = {pid: tree(project / both.get(pid).root) for pid in ("mt-a", "tts-a")}
    for pack_id, files in (("mt-a", MT_V1), ("tts-a", VOICE_FILES)):
        Fault(monkeypatch, 3, Crash())
        transport = FakeTransport(payloads_for(both.get(pack_id), files))
        with pytest.raises(Crash):
            download(project, both, files, transport=transport, pack_id=pack_id)
        monkeypatch.undo()
    blocked = project / both.get("mt-a").root

    def refuse(source: Path, target: Path) -> None:
        if blocked in target.parents:
            raise PermissionError(32, "sharing violation")
        source.replace(target)

    monkeypatch.setattr(journal_module, "move_file", refuse)
    caplog.set_level(logging.INFO, logger="lianiq.packs")
    with pytest.raises(RecoveryFailed) as caught:
        installer(project, both).recover()
    monkeypatch.undo()

    assert caught.value.recovered == ("tts-a",) and caught.value.failed == ("mt-a",)
    assert tree(project / both.get("tts-a").root) == expected["tts-a"]
    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "pack_id=mt-a" in text and "error=PermissionError" in text
    assert str(tmp_path) not in text

    assert installer(project, both).recover() == ("mt-a",)
    assert tree(project / ROOT) == expected["mt-a"]
    assert models_scratch(project) == []
