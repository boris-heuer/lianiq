"""CAP-0171 contract.md §5: staged install and update (Integration halves of AC-08, AC-09, AC-14).

A cancel or failure in any phase (transfer, check, swap, manifest write) deletes staging,
keeps the manifest and leaves the previous version in place and *Validated*.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _install_fixtures import (
    ACCEPTED,
    MANIFEST,
    MT_V1,
    MT_V2,
    NOW,
    FakeTransport,
    Fault,
    Progress,
    catalog_of,
    download,
    installer,
    models_scratch,
    mt_pack_entry,
    payloads_for,
    state,
    tree,
)

from lianiq.packs.errors import InstallCancelled, InstallFailed
from lianiq.packs.installer import FILES_IN_USE, InstallResult
from lianiq.packs.jobs import CancelToken, JobPhase
from lianiq.packs.manifest import Manifest
from lianiq.packs.pack_file import FILE_ALTERED, PACK_FILE_NAME, render_pack_file
from lianiq.packs.sources import DownloadSource
from lianiq.packs.state import PackState

ROOT = "models/opus-mt-de-zh"


@pytest.fixture
def v1(tmp_path: Path):
    return catalog_of(tmp_path / "c1", mt_pack_entry())


@pytest.fixture
def v2(tmp_path: Path):
    return catalog_of(tmp_path / "c2", mt_pack_entry(version="2", files=MT_V2))


def test_ac08_a_download_installs_files_pack_file_and_records(tmp_path, v1) -> None:
    project = tmp_path / "p"
    progress = Progress()
    result = download(project, v1, MT_V1, progress=progress)

    assert result == InstallResult("mt-a", "1", "download")
    pack = v1.get("mt-a")
    assert tree(project / ROOT) == {**MT_V1, PACK_FILE_NAME: render_pack_file(pack)}
    manifest = Manifest.read(project / MANIFEST)
    record = manifest.pack("mt-a")
    assert record is not None and record.source == "download"
    assert (record.installed_at, record.licence_accepted_at) == (NOW, ACCEPTED)
    paths = {item["path"] for item in manifest.artifacts if item.get("pack_id") == "mt-a"}
    assert paths == {f"{ROOT}/{name}" for name in [*MT_V1, PACK_FILE_NAME]}
    assert progress.phases() == [JobPhase.TRANSFER, JobPhase.CHECK, JobPhase.SWAP]
    checks = [(d, t) for p, d, t in progress.calls if p is JobPhase.CHECK]
    assert checks[-1] == (len(MT_V1), len(MT_V1))
    assert state(project, v1).state is PackState.VALIDATED
    assert models_scratch(project) == []


def test_other_files_under_the_root_stay(tmp_path, v1) -> None:
    project = tmp_path / "p"
    (project / ROOT).mkdir(parents=True)
    (project / ROOT / "notes.txt").write_bytes(b"mine")
    download(project, v1, MT_V1)
    assert (project / ROOT / "notes.txt").read_bytes() == b"mine"


def test_ac14_an_update_replaces_version_one(tmp_path, v1, v2) -> None:
    project = tmp_path / "p"
    download(project, v1, MT_V1)
    assert state(project, v2).update_available
    result = download(project, v2, MT_V2)

    assert result.version == "2"
    assert {k: v for k, v in tree(project / ROOT).items() if k != PACK_FILE_NAME} == MT_V2
    status = state(project, v2)
    assert (status.state, status.update_available) == (PackState.VALIDATED, False)
    assert models_scratch(project) == []


def assert_v1_kept(project: Path, v1, v2, before: dict[str, bytes], manifest: bytes) -> None:
    assert tree(project / ROOT) == before
    assert (project / MANIFEST).read_bytes() == manifest
    status = state(project, v2)
    assert (status.state, status.update_available) == (PackState.VALIDATED, True)
    assert state(project, v1).state is PackState.VALIDATED
    assert models_scratch(project) == []


def installed_v1(tmp_path: Path, v1) -> tuple[Path, dict[str, bytes], bytes]:
    project = tmp_path / "p"
    download(project, v1, MT_V1)
    return project, tree(project / ROOT), (project / MANIFEST).read_bytes()


def test_ac14_a_failed_transfer_keeps_version_one(tmp_path, v1, v2) -> None:
    project, before, manifest = installed_v1(tmp_path, v1)
    pack = v2.get("mt-a")
    transport = FakeTransport(payloads_for(pack, MT_V2), broken={pack.files[1].url: 0})
    with pytest.raises(InstallFailed):
        download(project, v2, MT_V2, transport=transport)
    assert_v1_kept(project, v1, v2, before, manifest)


def test_ac14_a_failed_check_keeps_version_one(tmp_path, v1, v2, monkeypatch) -> None:
    project, before, manifest = installed_v1(tmp_path, v1)
    from lianiq.packs import installer as installer_module

    monkeypatch.setattr(installer_module, "sha256_file", lambda path: "0" * 64)
    with pytest.raises(InstallFailed) as caught:
        download(project, v2, MT_V2)
    assert caught.value.reason == FILE_ALTERED.format(path=v2.get("mt-a").files[0].path)
    assert_v1_kept(project, v1, v2, before, manifest)


@pytest.mark.parametrize("at", [1, 2, 4, 5, 8])
def test_ac14_a_failed_move_during_the_swap_keeps_version_one(
    tmp_path, v1, v2, monkeypatch, at
) -> None:
    project, before, manifest = installed_v1(tmp_path, v1)
    Fault(monkeypatch, at, PermissionError(32, "sharing violation"))
    with pytest.raises(InstallFailed) as caught:
        download(project, v2, MT_V2)
    assert caught.value.reason == FILES_IN_USE
    assert_v1_kept(project, v1, v2, before, manifest)


def test_ac14_a_failed_manifest_write_keeps_version_one(tmp_path, v1, v2, monkeypatch) -> None:
    project, before, manifest = installed_v1(tmp_path, v1)

    def broken(self, path):
        raise OSError("disk full")

    monkeypatch.setattr(Manifest, "write", broken)
    with pytest.raises(InstallFailed):
        download(project, v2, MT_V2)
    monkeypatch.undo()
    assert_v1_kept(project, v1, v2, before, manifest)


@pytest.mark.parametrize("phase", [JobPhase.TRANSFER, JobPhase.CHECK, JobPhase.SWAP])
def test_ac14_a_cancel_in_any_phase_keeps_version_one(tmp_path, v1, v2, phase) -> None:
    project, before, manifest = installed_v1(tmp_path, v1)
    cancel = CancelToken()

    def progress(seen: JobPhase, done: int, total: int) -> None:
        if seen is phase:
            cancel.cancel()

    with pytest.raises(InstallCancelled):
        download(project, v2, MT_V2, progress=progress, cancel=cancel)
    assert_v1_kept(project, v1, v2, before, manifest)


@pytest.mark.parametrize("phase", [JobPhase.TRANSFER, JobPhase.CHECK, JobPhase.SWAP])
def test_ac09_a_cancelled_first_install_leaves_nothing(tmp_path, v1, phase) -> None:
    project = tmp_path / "p"
    cancel = CancelToken()

    def progress(seen: JobPhase, done: int, total: int) -> None:
        if seen is phase:
            cancel.cancel()

    with pytest.raises(InstallCancelled):
        download(project, v1, MT_V1, progress=progress, cancel=cancel)
    assert not (project / ROOT).exists()
    assert not (project / MANIFEST).exists()
    assert models_scratch(project) == []
    assert state(project, v1).state is PackState.DOWNLOADABLE


@pytest.mark.parametrize("at", [1, 3])
def test_ac09_a_failed_first_install_swap_leaves_nothing(tmp_path, v1, monkeypatch, at) -> None:
    project = tmp_path / "p"
    Fault(monkeypatch, at, OSError(5, "I/O error"))
    with pytest.raises(InstallFailed):
        download(project, v1, MT_V1)
    assert not (project / ROOT).exists()
    assert not (project / MANIFEST).exists()
    assert models_scratch(project) == []


def test_a_script_install_needs_no_licence_acceptance(tmp_path, v1) -> None:
    project = tmp_path / "p"
    pack = v1.get("mt-a")
    source = DownloadSource(FakeTransport(payloads_for(pack, MT_V1)), record_source="script")
    result = installer(project, v1).install(pack, source, None, Progress(), CancelToken())

    assert result.source == "script"
    record = Manifest.read(project / MANIFEST).pack("mt-a")
    assert record is not None and (record.source, record.licence_accepted_at) == ("script", None)


def test_an_app_install_needs_a_licence_acceptance(tmp_path, v1) -> None:
    pack = v1.get("mt-a")
    source = DownloadSource(FakeTransport(payloads_for(pack, MT_V1)))
    with pytest.raises(ValueError, match="licence"):
        installer(tmp_path / "p", v1).install(pack, source, None, Progress(), CancelToken())
