"""CAP-0171 AC-30 and contract.md §1: the pack catalog and its load rules."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest
from _pack_fixtures import MT_FILES, load_catalog, mt_entry, pack_entry, voice_entry, write_catalog

from lianiq.config import AppConfig
from lianiq.languages import BUILTIN_REGISTRY, DirectedEdge, Requirement, RequirementKind
from lianiq.languages.registry import Availability
from lianiq.packs.catalog import BUILTIN_CATALOG_PATH, PackCatalog, PackKind
from lianiq.packs.errors import PackCatalogError, UnknownPackError

# SHA-256 of the five German/Mandarin entries at f0506b1 (canonical JSON, sorted keys).
BASELINE_DIGEST = "5cf7a0e257cd747c51065eabc561482648c7af455303de4b4868bd3b4d259dd6"
HEX64 = re.compile(r"[0-9a-f]{64}")
BUILTIN_IDS = (
    "stt-faster-whisper-small",
    "mt-de-zh-hans",
    "mt-zh-hans-de",
    "mt-en-zh-hans",
    "mt-zh-hans-en",
    "tts-de-thorsten-medium",
    "tts-zh-hans-aishell3",
    "tts-en-us-ljspeech-high",
)


@pytest.fixture(scope="module")
def builtin() -> PackCatalog:
    return PackCatalog.load(BUILTIN_CATALOG_PATH, BUILTIN_REGISTRY)


def test_ac30_builtin_catalog_lists_the_builtin_packs(builtin: PackCatalog) -> None:
    assert BUILTIN_CATALOG_PATH.name == "builtin_catalog.json"
    assert BUILTIN_CATALOG_PATH.parent == Path(__file__).resolve().parents[2] / "lianiq/packs"
    assert tuple(pack.id for pack in builtin.packs()) == BUILTIN_IDS
    assert all(pack.version == "1" for pack in builtin.packs())
    kinds = [pack.kind for pack in builtin.packs()]
    assert kinds == [PackKind.RECOGNITION, *[PackKind.TRANSLATION] * 4, *[PackKind.VOICE] * 3]
    assert builtin.get("tts-zh-hans-aishell3").archive is not None


def test_ac30_provides_are_qualified_registry_ids_and_unique(builtin: PackCatalog) -> None:
    seen: set[tuple[PackKind, str]] = set()
    for pack in builtin.packs():
        for subject in pack.provides:
            if pack.kind is PackKind.TRANSLATION:
                edge = DirectedEdge.from_key(subject)
                assert edge.key == subject
                languages = [edge.source, edge.target]
            else:
                languages = [subject]
            for language in languages:
                definition = BUILTIN_REGISTRY.get(language)
                assert definition.id == language  # registry id, canonical case
                assert definition.availability is Availability.QUALIFIED
            assert (pack.kind, subject) not in seen
            seen.add((pack.kind, subject))
    assert len({pack.root for pack in builtin.packs()}) == len(BUILTIN_IDS)


def test_ac30_urls_are_https_and_digests_are_64_hex(builtin: PackCatalog) -> None:
    for pack in builtin.packs():
        assert pack.root.startswith("models/")
        assert pack.files
        for item in pack.files:
            assert HEX64.fullmatch(item.sha256)
            assert item.size > 0
            if pack.archive is None:
                assert item.url is not None
                assert item.url.startswith("https://huggingface.co/")
                assert f"/resolve/{pack.upstream_revision}/" in item.url
            else:
                assert item.url is None
        if pack.archive is not None:
            assert pack.archive.url.startswith("https://")
            assert HEX64.fullmatch(pack.archive.sha256)
            assert pack.download_bytes == pack.archive.size
        else:
            assert pack.download_bytes == pack.installed_bytes
        assert pack.installed_bytes == sum(item.size for item in pack.files)


def test_ac30_roots_equal_the_default_settings_paths(builtin: PackCatalog) -> None:
    config = AppConfig()
    settings = json.loads((BUILTIN_CATALOG_PATH.parents[2] / "config/settings.json").read_text())
    stt = builtin.get("stt-faster-whisper-small")
    assert stt.root == config.speech_to_text.model_path == settings["speech_to_text"]["model_path"]
    assert set(stt.provides) == set(config.speech_to_text.languages)
    for pack_id in ("mt-de-zh-hans", "mt-zh-hans-de", "mt-en-zh-hans", "mt-zh-hans-en"):
        pack = builtin.get(pack_id)
        (key,) = pack.provides
        assert pack.root == config.translation.edges[key].model_path
        assert pack.root == settings["translation"]["edges"][key]["model_path"]
    for pack_id in ("tts-de-thorsten-medium", "tts-zh-hans-aishell3", "tts-en-us-ljspeech-high"):
        pack = builtin.get(pack_id)
        (language,) = pack.provides
        voice = config.tts.voices[language]
        assert voice == settings["tts"]["voices"][language]
        listed = {f"{pack.root}/{item.path}" for item in pack.files}
        assert voice == pack.root or voice in listed


def test_ac30_files_match_the_download_script_pins(builtin: PackCatalog) -> None:
    piper = builtin.get("tts-de-thorsten-medium")
    assert [item.path for item in piper.files] == [
        "de_DE-thorsten-medium.onnx",
        "de_DE-thorsten-medium.onnx.json",
        "de_DE-thorsten-medium.MODEL_CARD.md",
    ]
    sherpa = builtin.get("tts-zh-hans-aishell3")
    assert sherpa.archive is not None
    assert sherpa.archive.size == 31_559_701
    assert sherpa.archive.sha256.startswith("ab468db3")
    assert len(sherpa.files) == 9
    marian = builtin.get("mt-de-zh-hans")
    assert "pytorch_model.bin" in {item.path for item in marian.files}
    assert "tf_model.h5" not in {item.path for item in marian.files}
    assert marian.upstream_revision.startswith("cf77098")


def test_ac02_english_packs_and_unchanged_baseline_entries(builtin: PackCatalog) -> None:
    expected = {
        "mt-en-zh-hans": ("en>zh-Hans", "models/opus-mt-en-zh", "Apache-2.0"),
        "mt-zh-hans-en": ("zh-Hans>en", "models/opus-mt-zh-en", "CC BY 4.0"),
        "tts-en-us-ljspeech-high": ("en", "models/piper-en_US-ljspeech-high", "MIT (repository)"),
    }
    for pack_id, (subject, root, licence) in expected.items():
        pack = builtin.get(pack_id)
        assert (pack.provides, pack.root) == ((subject,), root)
        assert pack.licence.startswith(licence)
    assert "Tiedemann" in builtin.get("mt-zh-hans-en").use_constraints
    voice = builtin.get("tts-en-us-ljspeech-high")
    assert [item.path for item in voice.files] == [
        "en_US-ljspeech-high.onnx",
        "en_US-ljspeech-high.onnx.json",
        "en_US-ljspeech-high.MODEL_CARD.md",
    ]
    assert builtin.get("stt-faster-whisper-small").provides == ("de", "zh-Hans", "en")
    entries = json.loads(BUILTIN_CATALOG_PATH.read_bytes())["packs"]
    baseline = [entry for entry in entries if entry["id"] not in expected]
    baseline[0]["provides"].remove("en")  # the recognition pack, first in the file
    canonical = json.dumps(baseline, sort_keys=True, ensure_ascii=False).encode()
    assert hashlib.sha256(canonical).hexdigest() == BASELINE_DIGEST


def test_for_requirement_maps_capabilities_and_devices(builtin: PackCatalog) -> None:
    def pack_for(kind: RequirementKind, subject: str | None = None) -> str | None:
        pack = builtin.for_requirement(Requirement(kind, subject))
        return None if pack is None else pack.id

    de, zh = (BUILTIN_REGISTRY.get(tag).id for tag in ("de", "zh-Hans"))
    assert pack_for(RequirementKind.RECOGNITION, de) == "stt-faster-whisper-small"
    assert pack_for(RequirementKind.RECOGNITION, zh) == "stt-faster-whisper-small"
    assert pack_for(RequirementKind.TRANSLATION, DirectedEdge(zh, de).key) == "mt-zh-hans-de"
    assert pack_for(RequirementKind.VOICE, de) == "tts-de-thorsten-medium"
    assert pack_for(RequirementKind.VOICE, "en") == "tts-en-us-ljspeech-high"
    assert pack_for(RequirementKind.VOICE, "es") is None
    for kind in (RequirementKind.MICROPHONE, RequirementKind.PLAYBACK):
        assert pack_for(kind) is None
    assert pack_for(RequirementKind.CALL_ENDPOINTS, "local_microphone") is None


def test_get_unknown_pack_raises(builtin: PackCatalog) -> None:
    with pytest.raises(UnknownPackError) as raised:
        builtin.get("mt-xx")
    assert raised.value.pack_id == "mt-xx"


def test_a_valid_fixture_catalog_loads(tmp_path: Path) -> None:
    packs = load_catalog(tmp_path, mt_entry(), voice_entry())
    assert [pack.id for pack in packs.packs()] == ["mt-a", "tts-a"]
    assert packs.get("mt-a").files[0].path == "pytorch_model.bin"


def _set(entry: dict[str, Any], key: str, value: Any) -> dict[str, Any]:
    return {**entry, key: value}


def _file(entry: dict[str, Any], **changes: Any) -> dict[str, Any]:
    return {**entry, "files": [{**entry["files"][0], **changes}, *entry["files"][1:]]}


ARCHIVE = {"url": "https://example.test/a.tar.bz2", "size": 3, "sha256": "a" * 64, "top_level": "a"}
INVALID: dict[str, list[dict[str, Any]]] = {
    "planned language": [_set(voice_entry(), "provides", ["es"])],
    "unknown language": [_set(voice_entry(), "provides", ["xx"])],
    "non-canonical id": [_set(voice_entry(), "provides", ["DE"])],
    "edge to a planned language": [_set(mt_entry(), "provides", ["de>es"])],
    "malformed edge": [_set(mt_entry(), "provides", ["de"])],
    "no provides": [_set(mt_entry(), "provides", [])],
    "root outside models": [_set(mt_entry(), "root", "elsewhere/opus")],
    "root traversal": [_set(mt_entry(), "root", "models/../config")],
    "duplicate root": [
        mt_entry(),
        _set(_set(voice_entry(), "root", "models/opus-mt-de-zh"), "id", "b"),
    ],
    "duplicate capability": [mt_entry(), _set(_set(mt_entry(), "id", "mt-b"), "root", "models/b")],
    "duplicate id": [mt_entry(), _set(mt_entry(), "root", "models/b")],
    "unknown kind": [_set(mt_entry(), "kind", "dictionary")],
    "empty version": [_set(mt_entry(), "version", "")],
    "no files": [_set(mt_entry(), "files", [])],
    "http url": [_file(mt_entry(), url="http://example.test/x")],
    "missing url": [_file(mt_entry(), url=None)],
    "url beside an archive": [_set(mt_entry(), "archive", ARCHIVE)],
    "short digest": [_file(mt_entry(), sha256="abc")],
    "upper-case digest": [_file(mt_entry(), sha256="A" * 64)],
    "negative size": [_file(mt_entry(), size=-1)],
    "boolean size": [_file(mt_entry(), size=True)],
    "unsafe file path": [_file(mt_entry(), path="../x.bin")],
    "absolute file path": [_file(mt_entry(), path="/x.bin")],
    "drive file path": [_file(mt_entry(), path="C:/x.bin")],
    "backslash file path": [_file(mt_entry(), path="sub\\x.bin")],
    "reserved pack file name": [_file(mt_entry(), path="lianiq-pack.json")],
    "duplicate file path": [_set(mt_entry(), "files", [mt_entry()["files"][0]] * 2)],
    "missing field": [{k: v for k, v in mt_entry().items() if k != "licence"}],
    "unknown field": [_set(mt_entry(), "extra", 1)],
    "http archive": [
        pack_entry(
            "v", "voice", ["de"], "models/v", MT_FILES, archive={**ARCHIVE, "url": "http://x"}
        )
    ],
}


@pytest.mark.parametrize("case", sorted(INVALID))
def test_load_rules_reject_an_invalid_catalog(tmp_path: Path, case: str) -> None:
    path = write_catalog(tmp_path / "catalog.json", INVALID[case])
    with pytest.raises(PackCatalogError) as raised:
        PackCatalog.load(path, BUILTIN_REGISTRY)
    assert raised.value.reason


@pytest.mark.parametrize(
    "payload", ["not json", "[]", '{"format": "other/v1", "packs": []}', '{"format": "x"}']
)
def test_load_rejects_an_unreadable_document(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "catalog.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(PackCatalogError):
        PackCatalog.load(path, BUILTIN_REGISTRY)
    with pytest.raises(PackCatalogError):
        PackCatalog.load(tmp_path / "absent.json", BUILTIN_REGISTRY)
