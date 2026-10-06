from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path


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
