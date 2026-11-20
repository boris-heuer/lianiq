"""``scripts/download_models.py`` is a thin CLI over ``lianiq.packs`` (CAP-0171 WI-02, AC-24).

The pins live in the built-in catalog; the script keeps its ``--component`` choices,
installs through ``PackInstaller`` with ``DownloadSource`` and writes ``source: "script"``
records. Every test uses a fake transport behind a socket guard.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lianiq.languages import BUILTIN_REGISTRY
from lianiq.packs.catalog import BUILTIN_CATALOG_PATH, PackCatalog, PackKind
from lianiq.packs.errors import ConnectionUnavailable
from lianiq.packs.manifest import Manifest

SCRIPT = Path(__file__).parents[1] / "scripts" / "download_models.py"
WHEN = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _no_network():
    def blocked(*_args, **_kwargs):
        raise AssertionError("socket guard: the script tests use no network")

    with pytest.MonkeyPatch.context() as guard:
        guard.setattr(socket.socket, "connect", blocked)
        guard.setattr(socket, "create_connection", blocked)
        guard.setattr(socket, "getaddrinfo", blocked)
        yield


def load_download_models_module():
    spec = importlib.util.spec_from_file_location("download_models", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def tiny_catalog(folder: Path) -> tuple[PackCatalog, dict[str, bytes]]:
    """The built-in catalog with one recognition, translation and voice pack of tiny files."""
    raw = json.loads(BUILTIN_CATALOG_PATH.read_text(encoding="utf-8"))
    kept, payloads, seen = [], {}, set()
    for entry in raw["packs"]:
        if entry["kind"] in seen or entry["archive"] is not None:
            continue
        seen.add(entry["kind"])
        for item in entry["files"]:
            data = f"{entry['id']}/{item['path']}".encode()
            item["size"], item["sha256"] = len(data), hashlib.sha256(data).hexdigest()
            payloads[item["url"]] = data
        kept.append(entry)
    path = folder / "catalog.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**raw, "packs": kept}), encoding="utf-8")
    return PackCatalog.load(path, BUILTIN_REGISTRY), payloads


class Transport:
    def __init__(self, payloads: dict[str, bytes], *, offline: bool = False) -> None:
        self.payloads, self.offline, self.opened = payloads, offline, []

    def open(self, url: str, timeout: float):
        self.opened.append(url)
        if self.offline:
            raise ConnectionUnavailable("huggingface.co")
        return io.BytesIO(self.payloads[url])


def test_the_script_keeps_its_component_choices() -> None:
    module = load_download_models_module()
    for component in ("all", "stt", "translation", "tts"):
        assert module.parse_args(["--component", component]).component == component
    assert module.parse_args([]).component == "all"
    with pytest.raises(SystemExit):
        module.parse_args(["--component", "everything"])


def test_components_select_built_in_packs_by_kind() -> None:
    module = load_download_models_module()
    packs = PackCatalog.load(BUILTIN_CATALOG_PATH, BUILTIN_REGISTRY)
    ids = {c: [p.id for p in module.selected_packs(packs, c)] for c in module.COMPONENTS}
    assert ids["all"] == [pack.id for pack in packs.packs()]
    assert ids["stt"] == ["stt-faster-whisper-small"]
    assert ids["translation"] == ["mt-de-zh-hans", "mt-zh-hans-de"]
    assert ids["tts"] == ["tts-de-thorsten-medium", "tts-zh-hans-aishell3"]
    assert module.COMPONENTS["tts"] == (PackKind.VOICE,)


def test_the_script_has_no_own_pins_and_no_hub_client() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "huggingface_hub" not in source
    assert "sha256=" not in source and "revision=" not in source
    assert "lianiq.packs" in source
    assert len(source.encode("utf-8")) < 6_000  # a thin CLI


def test_the_script_writes_script_records(tmp_path, capsys) -> None:
    module = load_download_models_module()
    packs, payloads = tiny_catalog(tmp_path / "c")
    transport = Transport(payloads)
    results = module.install_packs(
        "all", root=tmp_path, catalog=packs, transport=transport, clock=lambda: WHEN
    )

    assert [r.source for r in results] == ["script"] * len(packs.packs())
    manifest = Manifest.read(tmp_path / "models" / "model-manifest.json")
    assert {r.id for r in manifest.packs} == {p.id for p in packs.packs()}
    assert all(r.source == "script" and r.licence_accepted_at is None for r in manifest.packs)
    assert all(item["pack_id"] and item["size"] >= 0 for item in manifest.artifacts)
    assert sorted(transport.opened) == sorted(payloads)
    for pack in packs.packs():
        assert (tmp_path / pack.root / "lianiq-pack.json").is_file()
    assert "Installed" in capsys.readouterr().out


def test_main_reports_one_actionable_error(tmp_path, monkeypatch, capsys) -> None:
    module = load_download_models_module()
    packs, payloads = tiny_catalog(tmp_path / "c")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "load_catalog", lambda: packs)
    monkeypatch.setattr(module, "HttpsTransport", lambda: Transport(payloads, offline=True))

    assert module.main(["--component", "stt"]) == 1
    error = capsys.readouterr().err
    assert error.startswith("Model download failed:") and "huggingface.co" in error
    assert not (tmp_path / "models" / "faster-whisper-small").exists()


def test_main_succeeds_and_recovers_first(tmp_path, monkeypatch, capsys) -> None:
    module = load_download_models_module()
    packs, payloads = tiny_catalog(tmp_path / "c")
    leftover = tmp_path / "models" / ".lianiq-staging" / "old"
    leftover.mkdir(parents=True)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "load_catalog", lambda: packs)
    monkeypatch.setattr(module, "HttpsTransport", lambda: Transport(payloads))

    assert module.main(["--component", "translation"]) == 0
    assert not leftover.exists()
    assert "model-manifest.json" in capsys.readouterr().out
