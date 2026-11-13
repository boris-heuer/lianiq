"""GitHub-only egress proxy for the native-e2e VM (CAP-0174, contract section 4.4).

A small stdlib ``asyncio`` relay. It accepts only ``CONNECT <host>:443`` for host names in
``egress-allowlist.txt``, resolves the name on the host, connects only to public addresses,
and then copies bytes in both directions. There is no TLS interception: the proxy never
sees request content. Every refusal is logged with its reason; allowed tunnels are logged
with the host name only.

Started and stopped by ``Invoke-NativeE2eRun.ps1`` with ``egress-allowlist.txt``, and once per
image build by ``New-NativeE2eImage.ps1`` with the build-only ``activation-allowlist.txt``
(``--allowlist``); never run inside the guest.
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import logging
import re
import socket
import sys
from collections.abc import Iterable
from pathlib import Path

HTTPS_PORT = 443
MAX_HEAD_BYTES = 8192
HEAD_TIMEOUT_S = 10.0
CONNECT_TIMEOUT_S = 15.0
MAX_CLIENTS = 128
CHUNK = 65536

# One DNS label; ``*`` may appear once in the first label of an allow-list entry.
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_ENTRY_RE = re.compile(rf"^(?:{_LABEL}|[a-z0-9-]*\*[a-z0-9-]*)(?:\.{_LABEL})+$")
_HOST_RE = re.compile(rf"^{_LABEL}(?:\.{_LABEL})+$")
_REQUEST_RE = re.compile(r"^CONNECT (?P<host>[^\s:]+):(?P<port>[0-9]{1,5}) HTTP/1\.[01]$")

LOG = logging.getLogger("egress-proxy")


class Refused(Exception):
    """A request the proxy refuses; ``status`` is the HTTP status returned to the guest."""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


def parse_allowlist(text: str) -> tuple[str, ...]:
    """Return the entries of an allow-list file; raise ``ValueError`` on a malformed line.

    Format: one lower-case host name per line; ``#`` starts a comment line; blank lines are
    ignored. An entry may hold one ``*`` in its first label (for example
    ``*.actions.githubusercontent.com``); it then matches exactly one label there. IP
    literals, ports, schemes, paths and a bare ``*`` are rejected.
    """
    entries: list[str] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.count("*") > 1 or not _ENTRY_RE.match(line) or _is_ip_literal(line):
            raise ValueError(f"allow-list line {number} is not a host-name entry: {line!r}")
        first, _, rest = line.partition(".")
        if "*" in rest or "." not in rest and "*" in first:
            raise ValueError(f"allow-list line {number} has a wildcard above the first label")
        if line in entries:
            raise ValueError(f"allow-list line {number} repeats {line!r}")
        entries.append(line)
    if not entries:
        raise ValueError("allow-list is empty")
    return tuple(entries)


def _is_ip_literal(value: str) -> bool:
    try:
        ipaddress.ip_address(value.strip("[]"))
    except ValueError:
        return False
    return True


def normalise_host(host: str) -> str:
    """Lower-case a requested host name and drop one trailing dot; reject non-names."""
    name = host.strip().lower()
    name = name.removesuffix(".")
    if _is_ip_literal(name) or not _HOST_RE.match(name) or len(name) > 253:
        raise Refused(403, "host-not-a-name")
    return name


def host_allowed(host: str, allowlist: Iterable[str]) -> bool:
    """True iff the normalised ``host`` equals an entry or matches a wildcard entry."""
    for entry in allowlist:
        if "*" not in entry:
            if host == entry:
                return True
            continue
        first, _, rest = entry.partition(".")
        host_first, _, host_rest = host.partition(".")
        if host_rest != rest or not host_first:
            continue
        prefix, _, suffix = first.partition("*")
        if (
            len(host_first) >= len(prefix) + len(suffix)
            and host_first.startswith(prefix)
            and host_first.endswith(suffix)
        ):
            return True
    return False


def parse_connect(head: bytes) -> tuple[str, int]:
    """Parse the request head; return ``(host, port)`` or raise ``Refused``."""
    try:
        text = head.decode("ascii")
    except UnicodeDecodeError as exc:
        raise Refused(400, "bad-request") from exc
    request_line = text.split("\r\n", 1)[0]
    if not request_line.startswith("CONNECT "):
        raise Refused(405, "method-not-connect")
    match = _REQUEST_RE.match(request_line)
    if match is None:
        raise Refused(400, "bad-request")
    port = int(match["port"])
    if port != HTTPS_PORT:
        raise Refused(403, "port-not-443")
    return match["host"], port


def public_addresses(addresses: Iterable[str]) -> tuple[list[str], list[str]]:
    """Split resolved addresses into ``(public, refused)``; only public ones are dialled.

    Private, loopback, link-local, multicast, reserved, unspecified and shared (CGNAT)
    ranges are refused, including IPv4-mapped IPv6 forms of them.
    """
    public: list[str] = []
    refused: list[str] = []
    for value in addresses:
        address = ipaddress.ip_address(value.split("%", 1)[0])
        mapped = getattr(address, "ipv4_mapped", None)
        if mapped is not None:
            address = mapped
        target = public if address.is_global and not address.is_multicast else refused
        if str(address) not in target:
            target.append(str(address))
    return public, refused


def decide(head: bytes, allowlist: Iterable[str]) -> str:
    """Validate one request head against the allow-list; return the host name to resolve."""
    host, _port = parse_connect(head)
    name = normalise_host(host)
    if not host_allowed(name, allowlist):
        raise Refused(403, "host-not-allow-listed")
    return name


async def _read_head(reader: asyncio.StreamReader) -> bytes:
    head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), HEAD_TIMEOUT_S)
    if len(head) > MAX_HEAD_BYTES:
        raise Refused(431, "head-too-large")
    return head


async def _pipe(source: asyncio.StreamReader, sink: asyncio.StreamWriter) -> None:
    try:
        while chunk := await source.read(CHUNK):
            sink.write(chunk)
            await sink.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        sink.close()


class EgressProxy:
    def __init__(self, allowlist: tuple[str, ...]) -> None:
        self.allowlist = allowlist
        self.slots = asyncio.Semaphore(MAX_CLIENTS)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        client = peer[0] if peer else "?"
        async with self.slots:
            try:
                await self._serve(client, reader, writer)
            except Refused as refusal:
                LOG.warning("refused client=%s reason=%s", client, refusal.reason)
                await _reply(writer, refusal.status)
            except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
                LOG.warning("refused client=%s reason=bad-or-slow-request", client)
                await _reply(writer, 400)
            except (ConnectionError, OSError) as exc:
                LOG.warning("closed client=%s reason=%s", client, type(exc).__name__)
            finally:
                writer.close()

    async def _serve(
        self, client: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        name = decide(await _read_head(reader), self.allowlist)
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(name, HTTPS_PORT, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise Refused(502, f"resolve-failed host={name}") from exc
        public, refused = public_addresses(info[4][0] for info in infos)
        for address in refused:
            LOG.warning(
                "refused client=%s host=%s address=%s reason=non-public-address",
                client,
                name,
                address,
            )
        if not public:
            raise Refused(403, f"no-public-address host={name}")
        upstream_reader, upstream_writer = await self._dial(name, public)
        LOG.info("tunnel client=%s host=%s", client, name)
        writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        await writer.drain()
        await asyncio.gather(_pipe(reader, upstream_writer), _pipe(upstream_reader, writer))

    async def _dial(
        self, name: str, addresses: list[str]
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        for address in addresses:
            try:
                return await asyncio.wait_for(
                    asyncio.open_connection(address, HTTPS_PORT), CONNECT_TIMEOUT_S
                )
            except (OSError, TimeoutError):
                continue
        raise Refused(502, f"connect-failed host={name}")


async def _reply(writer: asyncio.StreamWriter, status: int) -> None:
    try:
        writer.write(f"HTTP/1.1 {status} Refused\r\nContent-Length: 0\r\n\r\n".encode("ascii"))
        await writer.drain()
    except (ConnectionError, OSError):
        pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GitHub-only CONNECT proxy for native-e2e.")
    parser.add_argument("--listen", required=True, help="Host address on the internal switch")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=Path(__file__).with_name("egress-allowlist.txt"),
    )
    parser.add_argument("--log", type=Path, help="Append the proxy log to this file")
    return parser.parse_args(argv)


async def serve(args: argparse.Namespace) -> None:
    proxy = EgressProxy(parse_allowlist(args.allowlist.read_text(encoding="utf-8")))
    server = await asyncio.start_server(proxy.handle, args.listen, args.port, limit=MAX_HEAD_BYTES)
    LOG.info("listening on %s:%s with %d entries", args.listen, args.port, len(proxy.allowlist))
    async with server:
        await server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if args.log is not None:
        handlers.append(logging.FileHandler(args.log, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers
    )
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError) as exc:
        LOG.error("proxy stopped: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
