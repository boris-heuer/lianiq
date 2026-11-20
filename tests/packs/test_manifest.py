"""CAP-0171 contract.md §3: manifest schema 1 with additive pack fields."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from _pack_fixtures import WHEN, load_catalog, mt_entry, record, sha, voice_entry

from lianiq.packs.catalog import PackDefinition
from lianiq.packs.errors import ManifestError
from lianiq.packs.manifest import Manifest, PackRecord
from lianiq.packs.pack_file import PACK_FILE_NAME, render_pack_file


@pytest.fixture
def mt(tmp_path: Path) -> PackDefinition:
    return load_catalog(tmp_path, mt_entry(), voice_entry()).get("mt-a")


def _payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_a_missing_manifest_reads_as_empty(tmp_path: Path) -> None:
    manifest = Manifest.read(tmp_path / "models/model-manifest.json")
    assert manifest.artifacts == ()
    assert manifest.packs == ()
    assert manifest.pack("mt-a") is None


@pytest.mark.parametrize(
    "text",
    [
        "{",
        "[]",
        '{"schema_version": 2, "artifacts": []}',
        '{"schema_version": 1, "artifacts": {}}',
        '{"schema_version": 1, "artifacts": [], "packs": [{"id": "x"}]}',
        '{"schema_version": 1, "artifacts": [], "packs": {}}',
    ],
)
def test_an_unreadable_manifest_raises(tmp_path: Path, text: str) -> None:
    path = tmp_path / "model-manifest.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ManifestError) as raised:
        Manifest.read(path)
    assert raised.value.reason


def test_with_pack_records_the_files_the_pack_file_and_the_pack(
    tmp_path: Path, mt: PackDefinition
) -> None:
    manifest = Manifest.read(tmp_path / "absent.json").with_pack(mt, record(mt))

    by_path = {item["path"]: item for item in manifest.artifacts}
    assert sorted(by_path) == [
        "models/opus-mt-de-zh/config.json",
        f"models/opus-mt-de-zh/{PACK_FILE_NAME}",
        "models/opus-mt-de-zh/pytorch_model.bin",
    ]
    weights = by_path["models/opus-mt-de-zh/pytorch_model.bin"]
    assert weights["pack_id"] == "mt-a"
    assert weights["size"] == mt.files[0].size
    assert weights["sha256"] == mt.files[0].sha256
    assert weights["revision"] == mt.upstream_revision
    assert weights["repo_id"] == "example/model"  # owner/name from the source URL
    pack_file = by_path[f"models/opus-mt-de-zh/{PACK_FILE_NAME}"]
    raw = render_pack_file(mt)
    assert (pack_file["size"], pack_file["sha256"]) == (len(raw), sha(raw))
    assert manifest.pack("mt-a") == record(mt)


def test_with_pack_replaces_older_records_and_keeps_others(
    tmp_path: Path, mt: PackDefinition
) -> None:
    path = tmp_path / "model-manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generator": "future",
                "artifacts": [
                    # An older script record of a listed file, without pack_id.
                    {"path": "models/opus-mt-de-zh/config.json", "sha256": "1" * 64},
                    # A record of the pack's previous version (a file no longer listed).
                    {"path": "models/opus-mt-de-zh/old.bin", "sha256": "2" * 64, "pack_id": "mt-a"},
                    {"path": "models/opus-mt-de-zh/notes.txt", "sha256": "3" * 64},
                    {"path": "models/piper/x.onnx", "sha256": "4" * 64, "future": [1]},
                ],
            }
        ),
        encoding="utf-8",
    )

    manifest = Manifest.read(path).with_pack(mt, record(mt))

    paths = [item["path"] for item in manifest.artifacts]
    assert "models/opus-mt-de-zh/old.bin" not in paths
    assert "models/opus-mt-de-zh/notes.txt" in paths  # unlisted file of another origin
    assert {"path": "models/piper/x.onnx", "sha256": "4" * 64, "future": [1]} in (
        manifest.artifacts
    )
    config = [i for i in manifest.artifacts if i["path"].endswith("/config.json")]
    assert len(config) == 1 and config[0]["pack_id"] == "mt-a"

    manifest.write(path)
    payload = _payload(path)
    assert payload["schema_version"] == 1
    assert payload["generator"] == "future"  # unknown top-level fields stay
    assert [item["path"] for item in payload["artifacts"]] == sorted(paths)


def test_without_pack_removes_its_records_with_or_without_pack_id(
    tmp_path: Path, mt: PackDefinition
) -> None:
    manifest = Manifest.read(tmp_path / "absent.json").with_pack(mt, record(mt))
    path = tmp_path / "model-manifest.json"
    manifest.write(path)
    payload = _payload(path)
    payload["artifacts"].append(
        {"path": "models/opus-mt-de-zh/pytorch_model.bin.bak", "sha256": "5" * 64}
    )
    payload["artifacts"].append({"path": "models/piper/x.onnx", "sha256": "4" * 64})
    script = {"path": "models/opus-mt-de-zh/config.json", "sha256": "1" * 64}
    payload["artifacts"] = [
        script if item["path"] == script["path"] else item for item in payload["artifacts"]
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")

    removed = Manifest.read(path).without_pack(mt)

    assert removed.pack("mt-a") is None
    assert [item["path"] for item in removed.artifacts] == [
        "models/opus-mt-de-zh/pytorch_model.bin.bak",
        "models/piper/x.onnx",
    ]
    assert script not in removed.artifacts


def test_write_round_trips_records_and_leaves_no_temporary_file(
    tmp_path: Path, mt: PackDefinition
) -> None:
    folder = tmp_path / "models"
    path = folder / "model-manifest.json"
    local = timezone(timedelta(hours=1))
    accepted = PackRecord(
        "mt-a",
        "1",
        "import",
        datetime(2026, 11, 19, 10, 15, 3, tzinfo=local),
        "Apache-2.0",
        datetime(2026, 11, 19, 10, 14, 40, tzinfo=local),
    )
    script = PackRecord("tts-a", "1", "script", WHEN, "MIT", None)
    voice = load_catalog(tmp_path / "v", voice_entry()).get("tts-a")

    Manifest.read(path).with_pack(mt, accepted).with_pack(voice, script).write(path)

    assert sorted(p.name for p in folder.iterdir()) == ["model-manifest.json"]
    payload = _payload(path)
    assert payload["packs"][0] == {
        "id": "mt-a",
        "version": "1",
        "source": "import",
        "installed_at": "2026-11-19T10:15:03+01:00",
        "licence": "Apache-2.0",
        "licence_accepted_at": "2026-11-19T10:14:40+01:00",
    }
    assert payload["packs"][1]["licence_accepted_at"] is None
    again = Manifest.read(path)
    assert again.pack("mt-a") == accepted
    assert again.pack("tts-a") == script
    assert again.packs == (accepted, script)


def test_a_failed_replace_leaves_the_old_manifest_and_no_temporary_file(
    tmp_path: Path, mt: PackDefinition, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "models"
    folder.mkdir()
    path = folder / "model-manifest.json"
    path.write_text('{"schema_version": 1, "artifacts": []}', encoding="utf-8")
    before = path.read_bytes()
    manifest = Manifest.read(path).with_pack(mt, record(mt))

    def fail(*_args: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        manifest.write(path)

    assert path.read_bytes() == before
    assert sorted(p.name for p in folder.iterdir()) == ["model-manifest.json"]


def test_pack_record_rejects_an_unknown_source() -> None:
    with pytest.raises(ValueError):
        PackRecord("mt-a", "1", "ftp", WHEN, "MIT", None)  # type: ignore[arg-type]


def test_digests_by_path(tmp_path: Path, mt: PackDefinition) -> None:
    manifest = Manifest.read(tmp_path / "absent.json").with_pack(mt, record(mt))
    digests = manifest.digests()
    assert digests["models/opus-mt-de-zh/pytorch_model.bin"] == mt.files[0].sha256
