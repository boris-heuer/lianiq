"""CAP-0171 contract.md §8 disk space (Integration half of AC-12).

``required_bytes`` is the installed size plus the archive (if any) plus 100 MiB; a job
re-checks free space at its start and stops with ``InsufficientSpace``, writing nothing.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from _install_fixtures import (
    MT_V1,
    archive_pack_entry,
    archive_tar,
    catalog_of,
    download,
    installer,
    mt_pack_entry,
    tree,
)

from lianiq.packs.disk import HEADROOM_BYTES, free_bytes, required_bytes
from lianiq.packs.errors import InsufficientSpace


def test_required_bytes_of_a_file_pack(tmp_path: Path) -> None:
    pack = catalog_of(tmp_path, mt_pack_entry()).get("mt-a")
    assert HEADROOM_BYTES == 100 * 1024 * 1024
    assert required_bytes(pack) == pack.installed_bytes + HEADROOM_BYTES


def test_required_bytes_of_an_archive_pack_counts_the_archive(tmp_path: Path) -> None:
    payload = archive_tar()
    pack = catalog_of(tmp_path, archive_pack_entry(payload)).get("tts-z")
    assert required_bytes(pack) == pack.installed_bytes + len(payload) + HEADROOM_BYTES


def test_free_bytes_of_a_models_folder_that_does_not_exist_yet(tmp_path: Path) -> None:
    folder = tmp_path / "project" / "models"
    free = free_bytes(folder)
    assert 0 < free <= shutil.disk_usage(tmp_path).total
    assert not folder.exists()


def test_free_bytes_of_an_existing_folder(tmp_path: Path) -> None:
    assert free_bytes(tmp_path) > 0


def test_ac12_a_job_stops_unchanged_when_space_dropped(tmp_path: Path) -> None:
    packs = catalog_of(tmp_path / "c", mt_pack_entry())
    project = tmp_path / "p"
    needed = required_bytes(packs.get("mt-a"))
    tight = installer(project, packs, free_space=lambda folder: needed - 1)

    with pytest.raises(InsufficientSpace) as caught:
        tight.check_space(packs.get("mt-a"))
    assert (caught.value.required, caught.value.free) == (needed, needed - 1)

    from _install_fixtures import ACCEPTED, FakeTransport, Progress, payloads_for

    from lianiq.packs.jobs import CancelToken
    from lianiq.packs.sources import DownloadSource

    source = DownloadSource(FakeTransport(payloads_for(packs.get("mt-a"), MT_V1)))
    with pytest.raises(InsufficientSpace):
        tight.install(packs.get("mt-a"), source, ACCEPTED, Progress(), CancelToken())
    assert tree(project) == {}
    assert source.transport.opened == []  # type: ignore[attr-defined]


def test_enough_space_lets_the_job_run(tmp_path: Path) -> None:
    packs = catalog_of(tmp_path / "c", mt_pack_entry())
    installer(tmp_path / "p", packs, free_space=lambda folder: 10**12).check_space(
        packs.get("mt-a")
    )
    download(tmp_path / "p", packs, MT_V1)
