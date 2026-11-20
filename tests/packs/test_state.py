"""CAP-0171 AC-23 and the Unit half of AC-17: every ``pack_status`` rule row (contract.md §4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _pack_fixtures import (
    MANIFEST,
    MT_FILES,
    VOICE_FILE,
    VOICE_FILES,
    capability_catalog,
    fixture_packs,
    install,
    load_catalog,
    mt_entry,
    script_install,
    sha,
    write_files,
)

from lianiq.config import AppConfig, TranslationEdgeConfig
from lianiq.languages import DirectedEdge, ReadinessStatus
from lianiq.packs.catalog import PackCatalog
from lianiq.packs.jobs import JobPhase, JobView
from lianiq.packs.manifest import Manifest
from lianiq.packs.pack_file import PACK_FILE_NAME
from lianiq.packs.state import PackState, PackStatus, pack_status


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return tmp_path / "project"


@pytest.fixture
def packs(tmp_path: Path) -> PackCatalog:
    return fixture_packs(tmp_path / "catalog")


def status(
    project: Path,
    packs: PackCatalog,
    pack_id: str,
    *,
    config: AppConfig | None = None,
    job: JobView | None = None,
    last_error: str | None = None,
) -> PackStatus:
    config = config or AppConfig()
    manifest = Manifest.read(project / "models/model-manifest.json")
    catalog = capability_catalog(project, packs, manifest, config)
    return pack_status(packs.get(pack_id), catalog, manifest, config, job, last_error)


def test_downloadable_with_an_empty_project(project: Path, packs: PackCatalog) -> None:
    assert status(project, packs, "mt-a") == PackStatus(PackState.DOWNLOADABLE, None, False, False)
    assert status(project, packs, "tts-a").state is PackState.DOWNLOADABLE


def test_installing_while_a_job_for_this_pack_runs(project: Path, packs: PackCatalog) -> None:
    job = JobView("mt-a", "install", JobPhase.TRANSFER, 10, 100)
    assert status(project, packs, "mt-a", job=job, last_error="x").state is PackState.INSTALLING
    other = JobView("tts-a", "install", JobPhase.CHECK, 1, 2)
    assert status(project, packs, "mt-a", job=other).state is PackState.DOWNLOADABLE


def test_failed_with_the_last_job_error(project: Path, packs: PackCatalog) -> None:
    result = status(project, packs, "mt-a", last_error="no connection to example.test")
    assert result == PackStatus(PackState.FAILED, "no connection to example.test", False, False)


def test_validated_after_an_app_install(project: Path, packs: PackCatalog) -> None:
    install(project, packs.get("mt-a"), MT_FILES)
    install(project, packs.get("tts-a"), VOICE_FILES)
    assert status(project, packs, "mt-a") == PackStatus(PackState.VALIDATED, None, False, False)
    assert status(project, packs, "tts-a").state is PackState.VALIDATED


def test_installed_after_an_older_script_install(project: Path, packs: PackCatalog) -> None:
    script_install(project, packs.get("mt-a"), MT_FILES)
    assert status(project, packs, "mt-a") == PackStatus(PackState.INSTALLED, None, False, False)


@pytest.mark.parametrize("name", list(MT_FILES))
def test_failed_when_a_listed_file_is_deleted(project: Path, packs: PackCatalog, name: str) -> None:
    install(project, packs.get("mt-a"), MT_FILES)
    (project / "models/opus-mt-de-zh" / name).unlink()
    assert status(project, packs, "mt-a") == PackStatus(
        PackState.FAILED, "1 file missing", False, False
    )


def test_failed_counts_every_missing_file(project: Path, packs: PackCatalog) -> None:
    install(project, packs.get("mt-a"), MT_FILES)
    for name in MT_FILES:
        (project / "models/opus-mt-de-zh" / name).unlink()
    assert status(project, packs, "mt-a").reason == "2 files missing"


@pytest.mark.parametrize("data", [b"x", b"same size altered"[: len(VOICE_FILES[VOICE_FILE])]])
def test_ac17_failed_when_a_file_the_probe_does_not_read_is_altered(
    project: Path, packs: PackCatalog, data: bytes
) -> None:
    install(project, packs.get("tts-a"), VOICE_FILES)
    # The CAP-0169 probe of a Piper voice reads only the .onnx; the .onnx.json counts too.
    (project / "models/piper" / f"{VOICE_FILE}.json").write_bytes(data)
    result = status(project, packs, "tts-a")
    assert result.state is PackState.FAILED
    assert result.reason == "integrity check failed"


def test_ac17_failed_when_the_piper_json_is_deleted(project: Path, packs: PackCatalog) -> None:
    install(project, packs.get("tts-a"), VOICE_FILES)
    (project / "models/piper" / f"{VOICE_FILE}.json").unlink()
    assert status(project, packs, "tts-a").reason == "1 file missing"


def test_failed_when_the_pack_file_of_a_record_is_missing(
    project: Path, packs: PackCatalog
) -> None:
    install(project, packs.get("mt-a"), MT_FILES)
    (project / "models/opus-mt-de-zh" / PACK_FILE_NAME).unlink()
    assert status(project, packs, "mt-a") == PackStatus(
        PackState.FAILED, "pack file missing", False, False
    )
    (project / "models/opus-mt-de-zh" / PACK_FILE_NAME).write_bytes(b"{")
    assert status(project, packs, "mt-a").reason == "pack file invalid"


def test_failed_when_a_provided_capability_is_invalid_without_record(
    project: Path, packs: PackCatalog
) -> None:
    script_install(project, packs.get("mt-a"), MT_FILES)
    (project / "models/opus-mt-de-zh/config.json").write_bytes(b"{" * len(MT_FILES["config.json"]))
    result = status(project, packs, "mt-a")
    assert result == PackStatus(PackState.FAILED, "integrity check failed", False, False)


def test_downloadable_with_a_partial_root_or_only_unlisted_files(
    project: Path, packs: PackCatalog
) -> None:
    write_files(
        project, "models/opus-mt-de-zh", {"pytorch_model.bin": MT_FILES["pytorch_model.bin"]}
    )
    assert status(project, packs, "mt-a").state is PackState.DOWNLOADABLE
    (project / "models/opus-mt-de-zh/pytorch_model.bin").unlink()
    write_files(project, "models/opus-mt-de-zh", {"notes.txt": b"unlisted"})
    assert status(project, packs, "mt-a").state is PackState.DOWNLOADABLE
    # Wrong-size listed files without a record make the capability invalid.
    write_files(project, "models/opus-mt-de-zh", {"pytorch_model.bin": b"x", "config.json": b"y"})
    assert status(project, packs, "mt-a").state is PackState.FAILED


def test_an_older_installed_version_is_judged_against_its_own_pack_file(
    project: Path, tmp_path: Path, packs: PackCatalog
) -> None:
    old_files = {"pytorch_model.bin": b"older weights"}
    old = load_catalog(tmp_path / "old", mt_entry("0", old_files)).get("mt-a")
    install(project, old, old_files)

    result = status(project, packs, "mt-a")

    assert result == PackStatus(PackState.VALIDATED, None, True, False)
    (project / "models/opus-mt-de-zh/pytorch_model.bin").write_bytes(b"older weightz")
    assert status(project, packs, "mt-a") == PackStatus(
        PackState.FAILED, "integrity check failed", True, False
    )


def test_update_available_only_with_a_record_of_another_version(
    project: Path, packs: PackCatalog
) -> None:
    script_install(project, packs.get("mt-a"), MT_FILES)
    assert status(project, packs, "mt-a").update_available is False
    install(project, packs.get("mt-a"), MT_FILES)
    assert status(project, packs, "mt-a").update_available is False


def test_custom_path_when_settings_point_outside_the_pack_root(
    project: Path, packs: PackCatalog
) -> None:
    config = AppConfig()
    edge_key = packs.get("mt-a").provides[0]
    config.translation.edges[edge_key] = TranslationEdgeConfig("models/custom-mt")
    write_files(project, "models/custom-mt", {"model.bin": b"custom"})
    result = status(project, packs, "mt-a", config=config)
    assert result.custom_path is True
    assert result.state is PackState.DOWNLOADABLE

    voice_config = AppConfig()
    voice_config.tts.voices["de"] = "models/piper/other-voice.onnx"
    assert status(project, packs, "tts-a", config=voice_config).custom_path is True
    assert status(project, packs, "tts-a").custom_path is False
    unset = AppConfig()
    unset.tts.voices["de"] = ""
    assert status(project, packs, "tts-a", config=unset).custom_path is False


def _custom_voice(project: Path) -> AppConfig:
    """Settings whose German voice lies outside the pack root (the CAP-0169 rules apply)."""
    config = AppConfig()
    config.tts.voices["de"] = "models/custom/voice.onnx"
    write_files(project, "models/custom", {"voice.onnx": b"custom"})
    return config


def test_validated_needs_a_packs_record(project: Path, packs: PackCatalog) -> None:
    config = _custom_voice(project)
    target = project / MANIFEST
    record = {"path": "models/custom/voice.onnx", "repo_id": "x/y", "sha256": sha(b"custom")}
    target.write_text(json.dumps({"schema_version": 1, "artifacts": [record]}), "utf-8")
    # The capability is CAP-0169 validated, but without a packs[] record the pack is not.
    assert status(project, packs, "tts-a", config=config) == PackStatus(
        PackState.DOWNLOADABLE, None, False, True
    )


@pytest.mark.parametrize("data", [b"X" * len(VOICE_FILES[f"{VOICE_FILE}.json"]), b"X"])
def test_a_record_with_an_altered_or_resized_listed_file_is_failed(
    project: Path, packs: PackCatalog, data: bytes
) -> None:
    install(project, packs.get("tts-a"), VOICE_FILES)
    # At a custom path the pack_files readiness rule does not apply; pack_status checks itself.
    config = _custom_voice(project)
    (project / "models/piper" / f"{VOICE_FILE}.json").write_bytes(data)
    assert status(project, packs, "tts-a", config=config) == PackStatus(
        PackState.FAILED, "integrity check failed", False, True
    )


def test_a_file_differing_from_its_manifest_record_is_altered(
    project: Path, packs: PackCatalog
) -> None:
    install(project, packs.get("mt-a"), MT_FILES)
    target = project / MANIFEST
    payload = json.loads(target.read_text("utf-8"))
    for item in payload["artifacts"]:
        if item["path"].endswith("/pytorch_model.bin"):
            item["sha256"] = "0" * 64
    target.write_text(json.dumps(payload), "utf-8")

    assert status(project, packs, "mt-a").reason == "integrity check failed"
    # Readiness judges the same digest, so modes agree with the pack state.
    manifest = Manifest.read(target)
    catalog = capability_catalog(project, packs, manifest)
    edge = DirectedEdge.from_key(packs.get("mt-a").provides[0])
    assert catalog.translation(edge).status is ReadinessStatus.INVALID


def test_a_parseable_but_altered_pack_file_is_failed(project: Path, packs: PackCatalog) -> None:
    install(project, packs.get("tts-a"), VOICE_FILES)
    config = _custom_voice(project)
    pack_file = project / "models/piper" / PACK_FILE_NAME
    pack_file.write_text(json.dumps(json.loads(pack_file.read_text("utf-8"))), "utf-8")
    assert status(project, packs, "tts-a", config=config) == PackStatus(
        PackState.FAILED, "integrity check failed", False, True
    )


def test_the_manifest_record_digest_counts_at_a_custom_path(
    project: Path, packs: PackCatalog
) -> None:
    install(project, packs.get("tts-a"), VOICE_FILES)
    config = _custom_voice(project)  # pack_status alone judges the listed files here
    target = project / MANIFEST
    payload = json.loads(target.read_text("utf-8"))
    for item in payload["artifacts"]:
        if item["path"].endswith(f"/{VOICE_FILE}.json"):
            item["sha256"] = "0" * 64
    target.write_text(json.dumps(payload), "utf-8")
    assert status(project, packs, "tts-a", config=config) == PackStatus(
        PackState.FAILED, "integrity check failed", False, True
    )
