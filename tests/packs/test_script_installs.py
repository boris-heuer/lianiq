"""CAP-0171 AC-24 (Integration): installs of old and new ``download_models.py`` are recognised.

``pack_status`` is computed for every pack of a catalog shaped exactly like the built-in one
(same ids, roots, listed paths and pinned URLs; a few bytes per file), the call the
Language packs page makes when it opens. Old-script installs show *Installed*, new-script
installs *Validated*, and the new script writes the app's records with ``source: script``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from _install_fixtures import (
    ACCEPTED,
    MANIFEST,
    NOW,
    FakeTransport,
    Progress,
    builtin_shaped,
    installer,
)
from _pack_fixtures import capability_catalog, sha, write_files

from lianiq.config import AppConfig
from lianiq.packs.jobs import CancelToken
from lianiq.packs.manifest import Manifest
from lianiq.packs.sources import DownloadSource
from lianiq.packs.state import PackState, pack_status

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "download_models.py"


def script_module():
    spec = importlib.util.spec_from_file_location("download_models_ac24", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def shaped(tmp_path: Path):
    return builtin_shaped(tmp_path / "catalog")


def states(project: Path, packs) -> dict[str, PackState]:
    manifest = Manifest.read(project / MANIFEST)
    catalog = capability_catalog(project, packs, manifest)
    config = AppConfig()
    return {
        pack.id: pack_status(pack, catalog, manifest, config, None, None).state
        for pack in packs.packs()
    }


def old_script_install(project: Path, packs, contents) -> None:
    """The layout and records of the pre-CAP-0171 script: artifacts only, no ``packs[]``."""
    artifacts = []
    for pack in packs.packs():
        write_files(project, pack.root, contents[pack.id])
        for name, data in contents[pack.id].items():
            artifacts.append(
                {
                    "path": f"{pack.root}/{name}",
                    "repo_id": "old/script",
                    "revision": pack.upstream_revision,
                    "sha256": sha(data),
                }
            )
    target = project / MANIFEST
    target.write_text(json.dumps({"schema_version": 1, "artifacts": artifacts}), "utf-8")


def new_script_install(project: Path, packs, payloads, component: str = "all"):
    transport = FakeTransport(payloads)
    module = script_module()
    results = module.install_packs(
        component, root=project, catalog=packs, transport=transport, clock=lambda: NOW
    )
    return results, transport


def test_ac24_the_built_in_shape_has_every_built_in_pack(shaped) -> None:
    packs, _, _ = shaped
    raw = json.loads(SCRIPT.parents[1].joinpath("lianiq/packs/builtin_catalog.json").read_text())
    assert [pack.id for pack in packs.packs()] == [entry["id"] for entry in raw["packs"]]


def test_ac24_old_script_installs_show_installed_without_download(tmp_path, shaped) -> None:
    packs, _, contents = shaped
    project = tmp_path / "old"
    old_script_install(project, packs, contents)

    assert states(project, packs) == {pack.id: PackState.INSTALLED for pack in packs.packs()}


def test_ac24_new_script_installs_show_validated(tmp_path, shaped) -> None:
    packs, payloads, _ = shaped
    project = tmp_path / "new"
    results, transport = new_script_install(project, packs, payloads)

    assert [r.pack_id for r in results] == [pack.id for pack in packs.packs()]
    assert {r.source for r in results} == {"script"}
    assert set(transport.opened) == set(payloads)  # only the pinned HTTPS URLs
    assert all(url.startswith("https://") for url in transport.opened)
    assert states(project, packs) == {pack.id: PackState.VALIDATED for pack in packs.packs()}
    manifest = Manifest.read(project / MANIFEST)
    for record in manifest.packs:
        assert (record.source, record.licence_accepted_at, record.installed_at) == (
            "script",
            None,
            NOW,
        )
    assert all("pack_id" in item and "size" in item for item in manifest.artifacts)


def test_ac24_the_new_script_writes_the_same_records_as_the_app(tmp_path, shaped) -> None:
    packs, payloads, _ = shaped
    script_project, app_project = tmp_path / "script", tmp_path / "app"
    new_script_install(script_project, packs, payloads)
    app = installer(app_project, packs)
    for pack in packs.packs():
        source = DownloadSource(FakeTransport(payloads))
        app.install(pack, source, ACCEPTED, Progress(), CancelToken())

    by_script = Manifest.read(script_project / MANIFEST)
    by_app = Manifest.read(app_project / MANIFEST)
    assert by_script.artifacts == by_app.artifacts
    for scripted, applied in zip(by_script.packs, by_app.packs, strict=True):
        assert (scripted.id, scripted.version, scripted.licence) == (
            applied.id,
            applied.version,
            applied.licence,
        )
        assert (scripted.source, applied.source) == ("script", "download")


def test_ac24_the_new_script_over_an_old_install_validates(tmp_path, shaped) -> None:
    packs, payloads, contents = shaped
    project = tmp_path / "upgrade"
    old_script_install(project, packs, contents)
    new_script_install(project, packs, payloads)
    assert states(project, packs) == {pack.id: PackState.VALIDATED for pack in packs.packs()}


def test_a_partial_component_keeps_the_other_records(tmp_path, shaped) -> None:
    packs, payloads, _ = shaped
    project = tmp_path / "partial"
    new_script_install(project, packs, payloads, "translation")
    first = Manifest.read(project / MANIFEST)
    new_script_install(project, packs, payloads, "tts")
    second = Manifest.read(project / MANIFEST)

    kinds = {pack.id: pack.kind.value for pack in packs.packs()}
    assert {r.id for r in first.packs} == {i for i, k in kinds.items() if k == "translation"}
    assert {r.id for r in second.packs} == {i for i, k in kinds.items() if k != "recognition"}
    assert all(item in second.artifacts for item in first.artifacts)
