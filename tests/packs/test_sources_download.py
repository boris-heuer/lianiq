"""CAP-0171 contract.md §5: ``DownloadSource`` and the HTTPS transport (fake transport only).

Bytes are untrusted until size and SHA-256 match; transfer reads 1 MiB blocks, stops at the
pinned size, honours a cancel between blocks and writes only catalog paths.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path

import pytest
from _install_fixtures import (
    ARCHIVE_FILES,
    ARCHIVE_TOP,
    ARCHIVE_URL,
    MT_V1,
    FakeTransport,
    Progress,
    archive_pack_entry,
    archive_tar,
    catalog_of,
    mt_pack_entry,
    payloads_for,
    tar_bytes,
    tree,
)

from lianiq.packs import sources
from lianiq.packs.errors import ConnectionUnavailable, InstallCancelled, InstallFailed
from lianiq.packs.jobs import CancelToken, JobPhase
from lianiq.packs.pack_file import FILE_ALTERED, FILE_MISSING, FILE_WRONG_SIZE
from lianiq.packs.sources import DownloadSource, HttpsTransport


@pytest.fixture
def mt(tmp_path: Path):
    return catalog_of(tmp_path / "c", mt_pack_entry()).get("mt-a")


def fetch(pack, transport, staging: Path, cancel: CancelToken | None = None) -> Progress:
    staging.mkdir(parents=True, exist_ok=True)
    progress = Progress()
    DownloadSource(transport).fetch(pack, staging, progress, cancel or CancelToken())
    return progress


def test_files_arrive_under_their_listed_paths_with_byte_progress(tmp_path, mt) -> None:
    transport = FakeTransport(payloads_for(mt, MT_V1))
    progress = fetch(mt, transport, tmp_path / "s")

    assert tree(tmp_path / "s") == MT_V1
    assert transport.opened == [item.url for item in mt.files]
    assert progress.phases() == [JobPhase.TRANSFER]
    assert progress.calls[-1] == (JobPhase.TRANSFER, mt.download_bytes, mt.download_bytes)
    assert all(total == mt.download_bytes for _, _, total in progress.calls)


def test_reads_are_capped_at_one_mib_blocks(tmp_path, monkeypatch) -> None:
    big = {"pytorch_model.bin": b"x" * (2 * 1024 * 1024 + 5), "config.json": b"{}"}
    pack = catalog_of(tmp_path / "c", mt_pack_entry(files=big)).get("mt-a")
    sizes: list[int] = []
    transport = FakeTransport(payloads_for(pack, big))
    original = transport.open

    def spying(url: str, timeout: float):
        stream = original(url, timeout)
        read = stream.read
        stream.read = lambda size=-1: (sizes.append(size), read(size))[1]  # type: ignore
        return stream

    transport.open = spying  # type: ignore[method-assign]
    fetch(pack, transport, tmp_path / "s")
    assert sizes and set(sizes) == {sources.BLOCK_BYTES}
    assert sources.BLOCK_BYTES == 1024 * 1024


@pytest.mark.parametrize(
    ("served", "reason"),
    [
        (b"weights v1 and more", FILE_WRONG_SIZE),
        (b"weights", FILE_WRONG_SIZE),
        (b"weights v2", FILE_ALTERED),
    ],
)
def test_a_wrong_size_or_digest_fails_the_transfer(tmp_path, mt, served, reason) -> None:
    payloads = payloads_for(mt, MT_V1)
    payloads[mt.files[0].url] = served
    with pytest.raises(InstallFailed) as caught:
        fetch(mt, FakeTransport(payloads), tmp_path / "s")
    assert caught.value.reason == reason.format(path=mt.files[0].path)


def test_a_larger_body_is_cut_at_the_pinned_size(tmp_path, mt) -> None:
    payloads = payloads_for(mt, MT_V1)
    payloads[mt.files[0].url] = b"w" * (5 * 1024 * 1024)
    with pytest.raises(InstallFailed):
        fetch(mt, FakeTransport(payloads), tmp_path / "s")
    written = tmp_path / "s" / mt.files[0].path
    assert not written.exists() or written.stat().st_size <= mt.files[0].size + sources.BLOCK_BYTES


def test_no_connection_names_the_host(tmp_path, mt) -> None:
    transport = FakeTransport({}, unavailable=frozenset({"files.example.test"}))
    with pytest.raises(ConnectionUnavailable) as caught:
        fetch(mt, transport, tmp_path / "s")
    assert caught.value.host == "files.example.test"


def test_a_dropped_connection_fails_the_transfer(tmp_path, mt) -> None:
    transport = FakeTransport(payloads_for(mt, MT_V1), broken={mt.files[0].url: 0})
    with pytest.raises(InstallFailed, match="transfer"):
        fetch(mt, transport, tmp_path / "s")


def test_cancel_is_honoured_between_blocks(tmp_path, mt) -> None:
    cancel = CancelToken()
    transport = FakeTransport(payloads_for(mt, MT_V1), on_read=lambda url, at: cancel.cancel())
    with pytest.raises(InstallCancelled):
        fetch(mt, transport, tmp_path / "s", cancel)
    assert cancel.cancelled


def test_a_non_https_file_url_is_never_opened(tmp_path, mt) -> None:
    plain = replace(mt.files[0], url="http://files.example.test/x")
    pack = replace(mt, files=(plain, *mt.files[1:]))
    transport = FakeTransport({})
    with pytest.raises(InstallFailed, match="HTTPS"):
        fetch(pack, transport, tmp_path / "s")
    assert transport.opened == []


# --- archive (moved from scripts/download_models.py) --------------------------------------


def archive_pack(tmp_path: Path, payload: bytes):
    return catalog_of(tmp_path / "c", archive_pack_entry(payload)).get("tts-z")


def test_an_archive_yields_only_its_listed_regular_files(tmp_path) -> None:
    payload = archive_tar({f"{ARCHIVE_TOP}/extra.py": b"x", "../escape/model.onnx": b"t"})
    pack = archive_pack(tmp_path, payload)
    transport = FakeTransport({ARCHIVE_URL: payload})
    progress = fetch(pack, transport, tmp_path / "job" / "pack")

    assert tree(tmp_path / "job" / "pack") == ARCHIVE_FILES
    assert transport.opened == [ARCHIVE_URL]
    assert progress.calls[-1] == (JobPhase.TRANSFER, len(payload), len(payload))
    assert not (tmp_path / "escape").exists()
    assert tree(tmp_path / "job") == {f"pack/{n}": d for n, d in ARCHIVE_FILES.items()}


@pytest.mark.parametrize(
    "members",
    [
        {f"{ARCHIVE_TOP}/model.onnx": ARCHIVE_FILES["model.onnx"]},  # tokens.txt missing
    ],
)
def test_an_archive_without_a_listed_file_fails(tmp_path, members) -> None:
    payload = tar_bytes(members)
    pack = archive_pack(tmp_path, payload)
    with pytest.raises(InstallFailed) as caught:
        fetch(pack, FakeTransport({ARCHIVE_URL: payload}), tmp_path / "j" / "p")
    assert caught.value.reason == FILE_MISSING.format(path="tokens.txt")


def test_a_linked_listed_member_fails(tmp_path) -> None:
    members = {f"{ARCHIVE_TOP}/model.onnx": ARCHIVE_FILES["model.onnx"]}
    payload = tar_bytes(members, symlink=f"{ARCHIVE_TOP}/tokens.txt")
    pack = archive_pack(tmp_path, payload)
    with pytest.raises(InstallFailed, match="tokens.txt"):
        fetch(pack, FakeTransport({ARCHIVE_URL: payload}), tmp_path / "j" / "p")


def test_a_duplicate_listed_member_fails(tmp_path) -> None:
    import io
    import tarfile

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:bz2") as bundle:
        for name, data in [*ARCHIVE_FILES.items(), ("tokens.txt", ARCHIVE_FILES["tokens.txt"])]:
            info = tarfile.TarInfo(f"{ARCHIVE_TOP}/{name}")
            info.size = len(data)
            bundle.addfile(info, io.BytesIO(data))
    payload = buffer.getvalue()
    pack = archive_pack(tmp_path, payload)
    with pytest.raises(InstallFailed, match="tokens.txt"):
        fetch(pack, FakeTransport({ARCHIVE_URL: payload}), tmp_path / "j" / "p")


def test_an_oversized_member_fails_before_writing(tmp_path, monkeypatch) -> None:
    payload = archive_tar()
    pack = archive_pack(tmp_path, payload)
    monkeypatch.setattr(sources, "MAX_EXTRACTED_FILE_BYTES", 4)
    with pytest.raises(InstallFailed, match="model.onnx"):
        fetch(pack, FakeTransport({ARCHIVE_URL: payload}), tmp_path / "j" / "p")
    assert not (tmp_path / "j" / "p" / "model.onnx").exists()


@pytest.mark.parametrize("change", [lambda d: d + b"x", lambda d: d[:-1] + bytes([d[-1] ^ 1])])
def test_an_archive_differing_from_its_pin_fails(tmp_path, change) -> None:
    payload = archive_tar()
    pack = archive_pack(tmp_path, payload)
    with pytest.raises(InstallFailed):
        fetch(pack, FakeTransport({ARCHIVE_URL: change(payload)}), tmp_path / "j" / "p")
    assert tree(tmp_path / "j" / "p") == {}


def test_an_unreadable_archive_fails(tmp_path) -> None:
    payload = b"not a tar archive at all"
    pack = archive_pack(tmp_path, payload)
    with pytest.raises(InstallFailed, match="archive"):
        fetch(pack, FakeTransport({ARCHIVE_URL: payload}), tmp_path / "j" / "p")


# --- the HTTPS transport (no socket is opened) --------------------------------------------


def test_the_transport_refuses_a_non_https_url() -> None:
    with pytest.raises(InstallFailed, match="HTTPS"):
        HttpsTransport().open("http://huggingface.co/x", timeout=1)


def test_a_redirect_to_a_non_https_url_fails() -> None:
    handler = sources.HttpsOnlyRedirects()
    request = urllib.request.Request("https://huggingface.co/x")
    with pytest.raises(InstallFailed, match="HTTPS"):
        handler.redirect_request(request, None, 302, "Found", {}, "http://cdn.example.test/x")
    followed = handler.redirect_request(request, None, 302, "Found", {}, "https://cdn.test/x")
    assert followed is not None and followed.full_url == "https://cdn.test/x"


def test_a_failed_connection_becomes_connection_unavailable(monkeypatch) -> None:
    transport = HttpsTransport()

    def unreachable(*_args, **_kwargs):
        raise urllib.error.URLError(OSError("getaddrinfo failed"))

    monkeypatch.setattr(transport, "_opener", type("O", (), {"open": staticmethod(unreachable)}))
    with pytest.raises(ConnectionUnavailable) as caught:
        transport.open("https://huggingface.co/x", timeout=1)
    assert caught.value.host == "huggingface.co"


def test_an_http_error_status_fails_the_transfer(monkeypatch) -> None:
    transport = HttpsTransport()

    def not_found(*_args, **_kwargs):
        raise urllib.error.HTTPError("https://huggingface.co/x", 404, "Not Found", {}, None)

    monkeypatch.setattr(transport, "_opener", type("O", (), {"open": staticmethod(not_found)}))
    with pytest.raises(InstallFailed, match="404"):
        transport.open("https://huggingface.co/x", timeout=1)


def test_the_transport_uses_the_system_proxy(monkeypatch) -> None:
    system = {"https": "http://proxy.example.test:8080"}
    monkeypatch.setattr(urllib.request, "getproxies", lambda: system)
    handlers = HttpsTransport()._opener.handlers
    proxies = [h for h in handlers if isinstance(h, urllib.request.ProxyHandler)]
    assert proxies and proxies[0].proxies == system
    assert any(isinstance(h, sources.HttpsOnlyRedirects) for h in handlers)
