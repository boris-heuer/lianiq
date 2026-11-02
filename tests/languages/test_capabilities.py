from __future__ import annotations

import json
from pathlib import Path

import pytest
from synthetic import (
    QAA,
    QAB,
    manifest_record,
    provisioned_catalog,
    synthetic_registry,
    write_manifest,
    write_model_directory,
    write_model_file,
)

from lianiq.config import AppConfig
from lianiq.languages import (
    BUILTIN_REGISTRY,
    CapabilityCatalog,
    DirectedEdge,
    LanguageId,
    ReadinessProbe,
    ReadinessStatus,
    SameLanguagePairError,
    UnknownLanguageError,
)

DE = LanguageId("de")
ZH = LanguageId("zh-Hans")
DE_ZH = DirectedEdge(DE, ZH)
ZH_DE = DirectedEdge(ZH, DE)


def test_directed_edge_key_round_trip_and_same_language_rejection() -> None:
    assert DE_ZH.key == "de>zh-Hans"
    assert DirectedEdge.from_key("de>zh-Hans") == DE_ZH
    assert DirectedEdge.from_key("ZH-HANS>DE") == ZH_DE
    assert DE_ZH.reversed() == ZH_DE
    assert DE_ZH != ZH_DE
    with pytest.raises(SameLanguagePairError):
        DirectedEdge(DE, DE)
    with pytest.raises(ValueError):
        DirectedEdge.from_key("de-zh")


def test_reverse_edge_is_never_derived_from_a_configured_edge(tmp_path: Path) -> None:
    catalog = provisioned_catalog(tmp_path, synthetic_registry(), edges=["qaa>qab"])

    forward = catalog.translation(DirectedEdge(QAA, QAB))
    reverse = catalog.translation(DirectedEdge(QAB, QAA))

    assert forward.status is ReadinessStatus.INSTALLED
    assert forward.status.is_ready
    assert reverse.status is ReadinessStatus.NOT_CONFIGURED
    assert reverse.model_path is None
    assert not reverse.status.is_ready
    assert catalog.recognition(QAA).status is ReadinessStatus.NOT_CONFIGURED
    assert catalog.voice(QAB).status is ReadinessStatus.NOT_CONFIGURED


def test_catalog_rejects_languages_outside_its_registry(tmp_path: Path) -> None:
    catalog = provisioned_catalog(tmp_path, synthetic_registry())

    with pytest.raises(UnknownLanguageError):
        catalog.voice(DE)
    with pytest.raises(UnknownLanguageError):
        CapabilityCatalog(
            synthetic_registry(), ReadinessProbe(tmp_path), voices={"de": tmp_path / "x.onnx"}
        )


def test_ac23_readiness_from_the_v1_download_manifest(tmp_path: Path) -> None:
    stt = write_model_directory(
        tmp_path, "models/faster-whisper-small", {"model.bin": b"stt", "config.json": b"{}"}
    )
    de_zh = write_model_directory(tmp_path, "models/opus-mt-de-zh", {"pytorch_model.bin": b"a"})
    zh_de = write_model_directory(tmp_path, "models/opus-mt-zh-de", {"pytorch_model.bin": b"b"})
    de_voice = write_model_file(tmp_path, "models/piper/de_DE-thorsten-medium.onnx", b"de")
    zh_voice = write_model_file(tmp_path, "models/piper/zh_CN-user-provided.onnx", b"zh")
    mismatched = manifest_record(tmp_path, zh_de / "pytorch_model.bin")
    mismatched["sha256"] = "0" * 64
    write_manifest(
        tmp_path,
        [
            # Validated: every record under the STT directory matches; unknown fields ignored.
            manifest_record(tmp_path, stt / "model.bin", future_field="ignored"),
            manifest_record(tmp_path, stt / "config.json"),
            manifest_record(tmp_path, de_zh / "pytorch_model.bin"),
            mismatched,
            manifest_record(tmp_path, de_voice),
            {"path": "models/unrelated/file.bin", "sha256": "1" * 64, "extra": [1, 2]},
            {"unknown": "record without path"},
        ],
        generator="future-download-tool",
    )
    probe = ReadinessProbe(tmp_path)
    catalog = CapabilityCatalog(
        BUILTIN_REGISTRY,
        probe,
        recognition={"de": Path("models/faster-whisper-small")},
        translation={DE_ZH: Path("models/opus-mt-de-zh"), ZH_DE: Path("models/opus-mt-zh-de")},
        voices={"de": de_voice, "zh-Hans": zh_voice},
    )

    assert catalog.recognition(DE).status is ReadinessStatus.VALIDATED
    assert catalog.translation(DE_ZH).status is ReadinessStatus.VALIDATED
    assert catalog.voice(DE).status is ReadinessStatus.VALIDATED
    # A voice file present without a manifest record is installed.
    assert catalog.voice(ZH).status is ReadinessStatus.INSTALLED
    # A mismatched digest is invalid.
    assert catalog.translation(ZH_DE).status is ReadinessStatus.INVALID
    assert probe.manifest_problem is None

    # An absent configured file or directory is missing.
    zh_voice.unlink()
    assert catalog.voice(ZH).status is ReadinessStatus.MISSING
    (stt / "model.bin").unlink()
    # A recorded file that is absent makes its capability invalid.
    assert catalog.recognition(DE).status is ReadinessStatus.INVALID
    missing_catalog = CapabilityCatalog(
        BUILTIN_REGISTRY, probe, translation={DE_ZH: Path("models/opus-mt-absent")}
    )
    assert missing_catalog.translation(DE_ZH).status is ReadinessStatus.MISSING


def test_ac23_directory_without_records_is_installed_and_without_manifest_too(
    tmp_path: Path,
) -> None:
    write_model_directory(tmp_path, "models/opus-mt-de-zh", {"pytorch_model.bin": b"a"})
    catalog = CapabilityCatalog(
        BUILTIN_REGISTRY,
        ReadinessProbe(tmp_path),
        translation={DE_ZH: Path("models/opus-mt-de-zh")},
    )

    assert catalog.translation(DE_ZH).status is ReadinessStatus.INSTALLED

    write_manifest(tmp_path, [{"path": "models/opus-mt-de-zh-other/x.bin", "sha256": "0" * 64}])
    catalog = CapabilityCatalog(
        BUILTIN_REGISTRY,
        ReadinessProbe(tmp_path),
        translation={DE_ZH: Path("models/opus-mt-de-zh")},
    )
    # A sibling directory sharing the name prefix does not own records of this directory.
    assert catalog.translation(DE_ZH).status is ReadinessStatus.INSTALLED


@pytest.mark.parametrize(
    "manifest_text",
    [
        "{not json",
        json.dumps({"schema_version": 2, "artifacts": []}),
        json.dumps(["not", "an", "object"]),
    ],
)
def test_ac23_unusable_manifest_reports_present_capabilities_as_installed(
    tmp_path: Path, manifest_text: str
) -> None:
    voice = write_model_file(tmp_path, "models/piper/de.onnx", b"de")
    manifest = tmp_path / "models" / "model-manifest.json"
    manifest.write_text(manifest_text, encoding="utf-8")
    probe = ReadinessProbe(tmp_path)
    catalog = CapabilityCatalog(BUILTIN_REGISTRY, probe, voices={"de": voice})

    assert catalog.voice(DE).status is ReadinessStatus.INSTALLED
    assert probe.manifest_problem is not None
    assert manifest.read_text(encoding="utf-8") == manifest_text


def test_hashing_is_lazy_per_required_capability_and_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    de_voice = write_model_file(tmp_path, "models/piper/de.onnx", b"de")
    zh_voice = write_model_file(tmp_path, "models/piper/zh.onnx", b"zh")
    write_manifest(
        tmp_path, [manifest_record(tmp_path, de_voice), manifest_record(tmp_path, zh_voice)]
    )
    probe = ReadinessProbe(tmp_path)
    hashed: list[str] = []
    original = ReadinessProbe._hash_file

    def counting_hash(path: Path) -> str:
        hashed.append(path.name)
        return original(path)

    monkeypatch.setattr(ReadinessProbe, "_hash_file", staticmethod(counting_hash))
    catalog = CapabilityCatalog(
        BUILTIN_REGISTRY, probe, voices={"de": de_voice, "zh-Hans": zh_voice}
    )
    assert hashed == []

    assert catalog.voice(DE).status is ReadinessStatus.VALIDATED
    assert catalog.voice(DE).status is ReadinessStatus.VALIDATED
    # Only the looked-up voice is hashed, and only once for an unchanged (path, size, mtime).
    assert hashed == ["de.onnx"]

    de_voice.write_bytes(b"changed")
    assert catalog.voice(DE).status is ReadinessStatus.INVALID
    assert hashed == ["de.onnx", "de.onnx"]


def test_from_config_maps_todays_v1_settings_to_directed_capabilities(tmp_path: Path) -> None:
    config = AppConfig()
    config.tts.zh_voice_path = ""
    write_model_directory(tmp_path, "models/opus-mt-de-zh", {"pytorch_model.bin": b"a"})
    write_model_file(tmp_path, "models/piper/de_DE-thorsten-medium.onnx")

    catalog = CapabilityCatalog.from_config(config, BUILTIN_REGISTRY, ReadinessProbe(tmp_path))

    assert catalog.translation(DE_ZH).status is ReadinessStatus.INSTALLED
    assert catalog.translation(DE_ZH).model_path == tmp_path / "models/opus-mt-de-zh"
    assert catalog.translation(ZH_DE).status is ReadinessStatus.MISSING
    assert catalog.recognition(DE).status is ReadinessStatus.MISSING
    assert catalog.recognition(ZH).status is ReadinessStatus.MISSING
    assert catalog.voice(DE).status is ReadinessStatus.INSTALLED
    assert catalog.voice(ZH).status is ReadinessStatus.NOT_CONFIGURED
