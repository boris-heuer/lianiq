from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
import tarfile
import types
from pathlib import Path

import pytest


def load_download_models_module():
    if "huggingface_hub" not in sys.modules:
        try:
            __import__("huggingface_hub")
        except ModuleNotFoundError:
            hub_stub = types.ModuleType("huggingface_hub")
            hub_stub.hf_hub_download = lambda **_kwargs: None
            hub_stub.snapshot_download = lambda **_kwargs: None
            sys.modules["huggingface_hub"] = hub_stub
    script = Path(__file__).parents[1] / "scripts" / "download_models.py"
    spec = importlib.util.spec_from_file_location("download_models", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_all_downloaded_sources_are_pinned_and_huayan_is_not_a_default() -> None:
    module = load_download_models_module()

    assert len(module.FASTER_WHISPER.revision) == 40
    assert all(len(spec.revision) == 40 for spec in module.MARIAN_SNAPSHOTS)
    assert len(module.PIPER_VOICES_REVISION) == 40
    assert all("huayan" not in spec.filename for spec in module.PIPER_VOICE_FILES)


def test_piper_download_records_pinned_revision_and_hash(tmp_path, monkeypatch) -> None:
    module = load_download_models_module()
    remote = tmp_path / "cached.onnx"
    remote.write_bytes(b"voice-bytes")
    destination = tmp_path / "models" / "voice.onnx"
    monkeypatch.setattr(module, "ROOT", tmp_path)
    seen = {}

    def fake_download(**kwargs):
        seen.update(kwargs)
        return remote

    monkeypatch.setattr(module, "hf_hub_download", fake_download)
    entry = module.download_piper_file(module.PiperFileSpec("de/test.onnx", destination))

    assert seen["revision"] == module.PIPER_VOICES_REVISION
    assert entry["sha256"] == module.sha256_file(destination)
    assert entry["revision"] == module.PIPER_VOICES_REVISION


def test_manifest_is_sorted_and_contains_sha256(tmp_path, monkeypatch) -> None:
    module = load_download_models_module()
    manifest = tmp_path / "models" / "model-manifest.json"
    monkeypatch.setattr(module, "MANIFEST", manifest)

    module.write_manifest(
        [
            {"path": "models/z", "repo_id": "b", "revision": "2", "sha256": "z"},
            {"path": "models/a", "repo_id": "a", "revision": "1", "sha256": "a"},
        ]
    )

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert [item["path"] for item in payload["artifacts"]] == ["models/a", "models/z"]


def test_partial_manifest_update_preserves_other_components_and_drops_stale_files(
    tmp_path, monkeypatch
) -> None:
    module = load_download_models_module()
    manifest = tmp_path / "models" / "model-manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "artifacts": [
                    {"path": "models/faster-whisper-small/model.bin", "sha256": "stt"},
                    {"path": "models/piper/obsolete.onnx", "sha256": "old"},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "MANIFEST", manifest)

    module.write_manifest(
        [{"path": "models/piper/current.onnx", "sha256": "new"}],
        replace_prefixes=("models/piper/",),
    )

    paths = [item["path"] for item in json.loads(manifest.read_text(encoding="utf-8"))["artifacts"]]
    assert paths == ["models/faster-whisper-small/model.bin", "models/piper/current.onnx"]


# --- WI-09: pinned sherpa-onnx Mandarin voice archive (untrusted until verified) ------------


def build_archive(path: Path, members: dict[str, bytes], *, symlink: str | None = None) -> None:
    with tarfile.open(path, "w:bz2") as bundle:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            bundle.addfile(info, io.BytesIO(data))
        if symlink is not None:
            info = tarfile.TarInfo(symlink)
            info.type = tarfile.SYMTYPE
            info.linkname = "../../outside"
            bundle.addfile(info)


def archive_spec(module, archive: Path, destination: Path, files=("model.onnx", "tokens.txt")):
    data = archive.read_bytes()
    return module.ArchiveSpec(
        url="https://example.invalid/voice.tar.bz2",
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        top_level="voice",
        files=files,
        destination=destination,
        repo_id="k2-fsa/sherpa-onnx",
    )


def test_sherpa_mandarin_voice_is_pinned_by_size_and_sha256() -> None:
    module = load_download_models_module()
    spec = module.SHERPA_MANDARIN_VOICE

    assert spec.url == (
        "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"
        "vits-icefall-zh-aishell3.tar.bz2"
    )
    assert spec.size == 31_559_701
    assert spec.sha256 == "ab468db3a3308cdd861495e0db2f25d79418a0c00639f74944c7cdf5dd8c6ec1"
    assert spec.destination == module.MODELS / "sherpa" / "vits-icefall-zh-aishell3"
    for required in ("model.onnx", "lexicon.txt", "tokens.txt", "rule.far", "new_heteronym.fst"):
        assert required in spec.files


def test_extract_takes_only_pinned_regular_files_by_listed_name(tmp_path) -> None:
    module = load_download_models_module()
    archive = tmp_path / "voice.tar.bz2"
    build_archive(
        archive,
        {
            "voice/model.onnx": b"model",
            "voice/tokens.txt": b"tokens",
            "voice/extra.py": b"print('not extracted')",
            "../escape/model.onnx": b"traversal",
        },
    )
    staging = tmp_path / "staging"
    staging.mkdir()

    module.extract_archive(archive_spec(module, archive, tmp_path / "dest"), archive, staging)

    assert sorted(path.name for path in staging.iterdir()) == ["model.onnx", "tokens.txt"]
    assert (staging / "model.onnx").read_bytes() == b"model"
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize(
    ("members", "symlink", "message"),
    [
        ({"voice/model.onnx": b"m"}, None, "lacks pinned files: tokens.txt"),
        ({"voice/model.onnx": b"m"}, "voice/tokens.txt", "Unexpected archive member"),
    ],
)
def test_extract_rejects_missing_files_and_links(tmp_path, members, symlink, message) -> None:
    module = load_download_models_module()
    archive = tmp_path / "voice.tar.bz2"
    build_archive(archive, members, symlink=symlink)
    staging = tmp_path / "staging"
    staging.mkdir()

    with pytest.raises(ValueError, match=message):
        module.extract_archive(archive_spec(module, archive, tmp_path / "d"), archive, staging)


def test_extract_refuses_an_archive_whose_hash_differs(tmp_path) -> None:
    module = load_download_models_module()
    archive = tmp_path / "voice.tar.bz2"
    build_archive(archive, {"voice/model.onnx": b"m", "voice/tokens.txt": b"t"})
    spec = archive_spec(module, archive, tmp_path / "d")
    build_archive(archive, {"voice/model.onnx": b"tampered", "voice/tokens.txt": b"t"})

    with pytest.raises(ValueError, match="SHA-256 does not match"):
        module.extract_archive(spec, archive, tmp_path)


def test_extract_rejects_an_oversized_member_before_writing(tmp_path, monkeypatch) -> None:
    module = load_download_models_module()
    archive = tmp_path / "voice.tar.bz2"
    build_archive(archive, {"voice/model.onnx": b"m" * 64, "voice/tokens.txt": b"t"})
    spec = archive_spec(module, archive, tmp_path / "d")
    staging = tmp_path / "staging"
    staging.mkdir()
    monkeypatch.setattr(module, "MAX_EXTRACTED_FILE_BYTES", 16)

    with pytest.raises(ValueError, match="too large"):
        module.extract_archive(spec, archive, staging)

    assert list(staging.iterdir()) == []


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def test_download_archive_verifies_extracts_and_records_the_manifest(tmp_path, monkeypatch) -> None:
    module = load_download_models_module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    archive = tmp_path / "voice.tar.bz2"
    build_archive(archive, {"voice/model.onnx": b"model", "voice/tokens.txt": b"tokens"})
    destination = tmp_path / "models" / "sherpa" / "voice"
    destination.mkdir(parents=True)
    (destination / "stale.bin").write_bytes(b"old")
    spec = archive_spec(module, archive, destination)
    payload = archive.read_bytes()
    monkeypatch.setattr(
        module.urllib.request, "urlopen", lambda url, timeout: FakeResponse(payload)
    )

    entries = module.download_archive(spec)

    assert sorted(path.name for path in destination.iterdir()) == ["model.onnx", "tokens.txt"]
    assert [entry["path"] for entry in entries] == [
        "models/sherpa/voice/model.onnx",
        "models/sherpa/voice/tokens.txt",
    ]
    assert entries[0]["sha256"] == hashlib.sha256(b"model").hexdigest()
    assert entries[0]["revision"] == f"{spec.url}#sha256={spec.sha256}"
    assert entries[0]["repo_id"] == "k2-fsa/sherpa-onnx"
    assert [path.name for path in destination.parent.iterdir()] == ["voice"]  # no temp left


@pytest.mark.parametrize(
    ("payload_change", "message"),
    [
        (lambda data: data + b"x", "larger than the pinned"),
        (lambda data: data[:-1], "expected"),
        # The download-time check names the URL and the received digest.
        (lambda data: data[:-1] + bytes([data[-1] ^ 1]), r"SHA-256 [0-9a-f]{64} does not match"),
    ],
)
def test_fetch_rejects_size_or_hash_differences_and_keeps_the_old_voice(
    tmp_path, monkeypatch, payload_change, message
) -> None:
    module = load_download_models_module()
    archive = tmp_path / "voice.tar.bz2"
    build_archive(archive, {"voice/model.onnx": b"model", "voice/tokens.txt": b"tokens"})
    destination = tmp_path / "models" / "sherpa" / "voice"
    destination.mkdir(parents=True)
    (destination / "model.onnx").write_bytes(b"kept")
    spec = archive_spec(module, archive, destination)
    changed = payload_change(archive.read_bytes())
    monkeypatch.setattr(
        module.urllib.request, "urlopen", lambda url, timeout: FakeResponse(changed)
    )

    with pytest.raises(ValueError, match=message):
        module.download_archive(spec)

    assert (destination / "model.onnx").read_bytes() == b"kept"


def test_fetch_archive_itself_rejects_a_hash_difference(tmp_path, monkeypatch) -> None:
    module = load_download_models_module()
    archive = tmp_path / "voice.tar.bz2"
    build_archive(archive, {"voice/model.onnx": b"model", "voice/tokens.txt": b"tokens"})
    spec = archive_spec(module, archive, tmp_path / "d")
    data = archive.read_bytes()
    tampered = data[:-1] + bytes([data[-1] ^ 1])
    monkeypatch.setattr(
        module.urllib.request, "urlopen", lambda url, timeout: FakeResponse(tampered)
    )

    with pytest.raises(ValueError, match=r"SHA-256 [0-9a-f]{64} does not match the pin"):
        module.fetch_archive(spec, tmp_path / "download.tar.bz2")
