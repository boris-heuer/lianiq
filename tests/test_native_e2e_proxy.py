"""Egress proxy and allow-list of the native-e2e VM (CAP-0174 WI-02, contract section 4.4).

The proxy is loaded from its file (its name has a hyphen) and only its pure decision
functions run here; no socket is opened.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "tools" / "native-e2e" / "host"
PROXY_PATH = HOST / "egress-proxy.py"
ALLOWLIST_PATH = HOST / "egress-allowlist.txt"


def load_proxy():
    spec = importlib.util.spec_from_file_location("native_e2e_egress_proxy", PROXY_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


proxy = load_proxy()
ALLOWLIST = proxy.parse_allowlist(ALLOWLIST_PATH.read_text(encoding="utf-8"))


def head(line: str) -> bytes:
    return f"{line}\r\nHost: x\r\n\r\n".encode("ascii")


def refusal(request: bytes) -> str:
    with pytest.raises(proxy.Refused) as caught:
        proxy.decide(request, ALLOWLIST)
    return caught.value.reason


def test_the_allowlist_holds_only_github_actions_and_results_storage_hosts() -> None:
    suffixes = (".github.com", ".githubusercontent.com", ".blob.core.windows.net")
    for entry in ALLOWLIST:
        assert entry == "github.com" or entry.endswith(suffixes), entry
    for required in ("github.com", "api.github.com", "*.actions.githubusercontent.com"):
        assert required in ALLOWLIST
    assert "*.blob.core.windows.net" not in ALLOWLIST  # never any storage account


@pytest.mark.parametrize(
    "text",
    [
        "",
        "# only a comment\n",
        "*\n",
        "*.com\n",
        "140.82.112.6\n",
        "github.com:443\n",
        "https://github.com\n",
        "api.github.com/repos\n",
        "a.*.github.com\n",
        "**.github.com\n",
        "GitHub.com\n",
        "github.com\ngithub.com\n",
    ],
)
def test_a_malformed_allowlist_is_rejected(text: str) -> None:
    with pytest.raises(ValueError):
        proxy.parse_allowlist(text)


def test_comments_and_blank_lines_are_ignored() -> None:
    assert proxy.parse_allowlist("# c\n\n  api.github.com  \n") == ("api.github.com",)


@pytest.mark.parametrize(
    "host",
    [
        "github.com",
        "API.GitHub.com.",
        "pipelines.actions.githubusercontent.com",
        "results-receiver.actions.githubusercontent.com",
        "productionresultssa7.blob.core.windows.net",
    ],
)
def test_https_connect_to_an_allow_listed_host_is_relayed(host: str) -> None:
    assert proxy.decide(head(f"CONNECT {host}:443 HTTP/1.1"), ALLOWLIST) == (
        host.lower().rstrip(".")
    )


@pytest.mark.parametrize(
    ("line", "reason"),
    [
        ("CONNECT example.com:443 HTTP/1.1", "host-not-allow-listed"),
        ("CONNECT evilgithub.com:443 HTTP/1.1", "host-not-allow-listed"),
        ("CONNECT github.com.evil.test:443 HTTP/1.1", "host-not-allow-listed"),
        ("CONNECT a.b.actions.githubusercontent.com:443 HTTP/1.1", "host-not-allow-listed"),
        ("CONNECT someone.blob.core.windows.net:443 HTTP/1.1", "host-not-allow-listed"),
        ("CONNECT 140.82.112.6:443 HTTP/1.1", "host-not-a-name"),
        ("CONNECT 192.168.1.10:443 HTTP/1.1", "host-not-a-name"),
        ("CONNECT localhost:443 HTTP/1.1", "host-not-a-name"),
        ("CONNECT github.com:80 HTTP/1.1", "port-not-443"),
        ("CONNECT github.com:22 HTTP/1.1", "port-not-443"),
        ("GET http://github.com/ HTTP/1.1", "method-not-connect"),
        ("CONNECT github.com HTTP/1.1", "bad-request"),
        ("CONNECT [::1]:443 HTTP/1.1", "bad-request"),
    ],
)
def test_everything_else_is_refused_with_a_reason(line: str, reason: str) -> None:
    assert refusal(head(line)) == reason


def test_a_non_ascii_request_is_refused() -> None:
    assert refusal("CONNECT gïthub.com:443 HTTP/1.1\r\n\r\n".encode()) == "bad-request"


def test_only_public_addresses_are_dialled() -> None:
    public, refused = proxy.public_addresses(
        [
            "140.82.112.6",
            "2606:50c0:8000::154",
            "10.0.0.5",
            "172.16.0.1",
            "192.168.250.1",
            "169.254.10.10",
            "127.0.0.1",
            "100.64.0.1",
            "0.0.0.0",
            "224.0.0.1",
            "::1",
            "fe80::1%12",
            "fd00::1",
            "::ffff:10.1.2.3",
        ]
    )
    assert public == ["140.82.112.6", "2606:50c0:8000::154"]
    assert len(refused) == 12


def test_the_proxy_uses_the_standard_library_only() -> None:
    tree = ast.parse(PROXY_PATH.read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert imported - {"__future__"} <= set(sys.stdlib_module_names)
    assert "ssl" not in imported  # no TLS interception


def test_the_relay_never_reads_request_content_after_connect() -> None:
    source = PROXY_PATH.read_text(encoding="utf-8")
    assert "Connection established" in source
    assert source.count("readuntil(") == 1  # only the CONNECT head is parsed
