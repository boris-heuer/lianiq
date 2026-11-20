"""CAP-0171 amendment of ``lianiq.language.readiness-status.v1``: ``pack_files`` and ``invalidate``.

A capability whose resolved path is a key of ``pack_files`` is judged by every listed file of
its pack; custom paths keep the CAP-0169 rules (contract.md §4).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from synthetic import write_model_directory, write_model_file

from lianiq.config import AppConfig
from lianiq.languages import (
    BUILTIN_REGISTRY,
    CapabilityCatalog,
    DirectedEdge,
    LanguageId,
    ReadinessProbe,
    ReadinessStatus,
)
from lianiq.packs.catalog import PackFile

DE = LanguageId("de")
ZH = LanguageId("zh-Hans")
DE_ZH = DirectedEdge(DE, ZH)
MT = "models/opus-mt-de-zh"
VOICE = "models/piper/de_DE-thorsten-medium.onnx"
MT_FILES = {"pytorch_model.bin": b"weights", "config.json": b"{}"}
VOICE_FILES = {"de_DE-thorsten-medium.onnx": b"voice", "de_DE-thorsten-medium.onnx.json": b"{}"}


def listed(root: str, files: dict[str, bytes]) -> tuple[PackFile, ...]:
    return tuple(
        PackFile(f"{root}/{name}", len(data), hashlib.sha256(data).hexdigest(), None)
        for name, data in files.items()
    )


def pack_files() -> dict[str, tuple[PackFile, ...]]:
    return {MT: listed(MT, MT_FILES), VOICE: listed("models/piper", VOICE_FILES)}


def write_manifest(root: Path, files: dict[str, dict[str, bytes]], *, pack_id: str | None) -> None:
    artifacts = []
    for folder, contents in files.items():
        for name, data in contents.items():
            item = {"path": f"{folder}/{name}", "sha256": hashlib.sha256(data).hexdigest()}
            if pack_id is not None:
                item["pack_id"] = pack_id
            artifacts.append(item)
    packs = [] if pack_id is None else [{"id": pack_id, "version": "1"}]
    path = root / "models/model-manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, "artifacts": artifacts, "packs": packs}))


def catalog(root: Path, config: AppConfig | None = None, **probe_args) -> CapabilityCatalog:
    probe = ReadinessProbe(root, **probe_args)
    return CapabilityCatalog.from_config(config or AppConfig(), BUILTIN_REGISTRY, probe)


def test_an_empty_or_partial_default_directory_is_missing(tmp_path: Path) -> None:
    (tmp_path / MT).mkdir(parents=True)
    assert catalog(tmp_path).translation(DE_ZH).status is ReadinessStatus.INSTALLED  # CAP-0169
    assert catalog(tmp_path, pack_files=pack_files()).translation(DE_ZH).status is (
        ReadinessStatus.MISSING
    )
    write_model_directory(tmp_path, MT, {"pytorch_model.bin": MT_FILES["pytorch_model.bin"]})
    assert catalog(tmp_path, pack_files=pack_files()).translation(DE_ZH).status is (
        ReadinessStatus.MISSING
    )


@pytest.mark.parametrize("data", [b"{}{}", b"[]"])
def test_a_wrong_size_or_digest_is_invalid(tmp_path: Path, data: bytes) -> None:
    write_model_directory(tmp_path, MT, {**MT_FILES, "config.json": data})
    status = catalog(tmp_path, pack_files=pack_files()).translation(DE_ZH).status
    assert status is ReadinessStatus.INVALID


def test_validated_with_a_packs_record_and_installed_without(tmp_path: Path) -> None:
    write_model_directory(tmp_path, MT, MT_FILES)
    write_manifest(tmp_path, {MT: MT_FILES}, pack_id=None)  # an older script install
    assert catalog(tmp_path).translation(DE_ZH).status is ReadinessStatus.VALIDATED  # CAP-0169
    assert catalog(tmp_path, pack_files=pack_files()).translation(DE_ZH).status is (
        ReadinessStatus.INSTALLED
    )
    write_manifest(tmp_path, {MT: MT_FILES}, pack_id="mt-de-zh-hans")
    assert catalog(tmp_path, pack_files=pack_files()).translation(DE_ZH).status is (
        ReadinessStatus.VALIDATED
    )


def test_a_voice_file_is_missing_without_its_json(tmp_path: Path) -> None:
    write_model_file(tmp_path, VOICE, VOICE_FILES["de_DE-thorsten-medium.onnx"])
    assert catalog(tmp_path).voice(DE).status is ReadinessStatus.INSTALLED  # CAP-0169
    assert catalog(tmp_path, pack_files=pack_files()).voice(DE).status is ReadinessStatus.MISSING
    write_model_file(tmp_path, f"{VOICE}.json", b"{")
    assert catalog(tmp_path, pack_files=pack_files()).voice(DE).status is ReadinessStatus.INVALID


def test_custom_paths_keep_the_cap0169_rules(tmp_path: Path) -> None:
    config = AppConfig()
    config.tts.voices["de"] = "models/custom/voice.onnx"
    write_model_file(tmp_path, "models/custom/voice.onnx", b"custom")
    assert catalog(tmp_path, config, pack_files=pack_files()).voice(DE).status is (
        ReadinessStatus.INSTALLED
    )


def test_keys_are_normalised_posix_paths(tmp_path: Path) -> None:
    write_model_directory(tmp_path, MT, MT_FILES)
    files = {"models\\opus-mt-de-zh/": listed(MT, MT_FILES)}
    assert catalog(tmp_path, pack_files=files).translation(DE_ZH).status is (
        ReadinessStatus.INSTALLED
    )


def test_an_older_installed_version_is_judged_against_its_own_pack_file(tmp_path: Path) -> None:
    from lianiq.packs.catalog import PackCatalog
    from lianiq.packs.manifest import Manifest, PackRecord
    from lianiq.packs.pack_file import render_pack_file
    from lianiq.packs.state import readiness_pack_files

    def entry(version: str, files: dict[str, bytes]) -> dict:
        return {
            "id": "mt-x",
            "version": version,
            "kind": "translation",
            "provides": [DE_ZH.key],
            "root": MT,
            "archive": None,
            "publisher": "p",
            "source_url": "https://e.test/p/m",
            "model": "m",
            "upstream_revision": "r",
            "licence": "MIT",
            "use_constraints": "",
            "files": [
                {
                    "path": n,
                    "size": len(d),
                    "sha256": hashlib.sha256(d).hexdigest(),
                    "url": f"https://e.test/{n}",
                }
                for n, d in files.items()
            ],
        }

    def load(name: str, version: str, files: dict[str, bytes]) -> PackCatalog:
        path = tmp_path / name
        path.write_text(
            json.dumps({"format": "lianiq-catalog/v1", "packs": [entry(version, files)]})
        )
        return PackCatalog.load(path, BUILTIN_REGISTRY)

    old_files = {"pytorch_model.bin": b"old weights"}
    old = load("old.json", "0", old_files).get("mt-x")
    current = load("current.json", "1", MT_FILES)
    write_model_directory(tmp_path, MT, old_files)
    (tmp_path / MT / "lianiq-pack.json").write_bytes(render_pack_file(old))
    record = PackRecord("mt-x", "0", "download", datetime(2026, 11, 19, tzinfo=UTC), "MIT", None)
    manifest = Manifest.read(tmp_path / "models/model-manifest.json").with_pack(old, record)
    manifest.write(tmp_path / "models/model-manifest.json")

    files = readiness_pack_files(current, manifest, AppConfig(), tmp_path)

    assert {item.path for item in files[MT]} >= {f"{MT}/pytorch_model.bin"}
    assert f"{MT}/config.json" not in {item.path for item in files[MT]}
    assert catalog(tmp_path, pack_files=files).translation(DE_ZH).status is (
        ReadinessStatus.VALIDATED
    )
    (tmp_path / MT / "pytorch_model.bin").write_bytes(b"old weightz")
    assert catalog(tmp_path, pack_files=files).translation(DE_ZH).status is (
        ReadinessStatus.INVALID
    )


def test_invalidate_clears_the_manifest_and_digest_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_model_directory(tmp_path, MT, MT_FILES)
    write_manifest(tmp_path, {MT: MT_FILES}, pack_id=None)
    probe = ReadinessProbe(tmp_path, pack_files=pack_files())
    hashed: list[str] = []
    original = ReadinessProbe._hash_file

    def counting_hash(path: Path) -> str:
        hashed.append(path.name)
        return original(path)

    monkeypatch.setattr(ReadinessProbe, "_hash_file", staticmethod(counting_hash))
    mt = CapabilityCatalog.from_config(AppConfig(), BUILTIN_REGISTRY, probe)
    assert mt.translation(DE_ZH).status is ReadinessStatus.INSTALLED
    count = len(hashed)
    assert count == 2
    write_manifest(tmp_path, {MT: MT_FILES}, pack_id="mt-de-zh-hans")
    assert mt.translation(DE_ZH).status is ReadinessStatus.INSTALLED  # manifest cached
    assert len(hashed) == count  # digests cached

    probe.invalidate()

    assert mt.translation(DE_ZH).status is ReadinessStatus.VALIDATED
    assert len(hashed) == 2 * count
    assert probe.verifier is mt.probe.verifier


def test_invalidate_forgets_pack_ownership_when_the_manifest_goes(tmp_path: Path) -> None:
    write_model_directory(tmp_path, MT, MT_FILES)
    write_manifest(tmp_path, {MT: MT_FILES}, pack_id="mt-de-zh-hans")
    probe = ReadinessProbe(tmp_path, pack_files=pack_files())
    mt = CapabilityCatalog.from_config(AppConfig(), BUILTIN_REGISTRY, probe)
    assert mt.translation(DE_ZH).status is ReadinessStatus.VALIDATED
    (tmp_path / "models/model-manifest.json").write_text("{ not json", "utf-8")

    probe.invalidate()

    assert mt.translation(DE_ZH).status is ReadinessStatus.INSTALLED


def test_a_manifest_record_digest_counts_over_the_listed_digest(tmp_path: Path) -> None:
    write_model_directory(tmp_path, MT, MT_FILES)
    write_manifest(tmp_path, {MT: MT_FILES}, pack_id="mt-de-zh-hans")
    path = tmp_path / "models/model-manifest.json"
    payload = json.loads(path.read_text())
    payload["artifacts"][0]["sha256"] = "0" * 64  # the record no longer matches the file
    path.write_text(json.dumps(payload))
    assert catalog(tmp_path, pack_files=pack_files()).translation(DE_ZH).status is (
        ReadinessStatus.INVALID
    )
