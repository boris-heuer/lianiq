"""The virtual cable for E-11 and E-03 (CAP-0174 contract §5, §6, §7.3 N-01).

VB-Cable has two endpoints: the app records from "CABLE Output" (capture) and the row plays
the N-01 test phrase into "CABLE Input" (render). PortAudio lists each endpoint once per host
API; ``pick_index`` prefers the given host API (the default one for playback and for the
legacy index, WASAPI for the name the app shows) and falls back to the first entry.

``sounddevice`` (app lock) and numpy are imported lazily; the endpoint identities come from
the app's own read-only registry reader. No function returns an endpoint name or identifier
into the evidence: callers compare them or hand them to the redaction scan and the mask.
"""

from __future__ import annotations

import wave
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from native_e2e.context import CABLE_NAMES
from native_e2e.evidence.sums import file_sha256

if TYPE_CHECKING:
    from native_e2e.context import RunContext

CABLE_INPUT, CABLE_OUTPUT = CABLE_NAMES
_CHANNELS = {"input": "max_input_channels", "output": "max_output_channels"}


def _sd() -> Any:
    import sounddevice

    return sounddevice


def devices() -> list[dict[str, Any]]:
    return [dict(device, index=index) for index, device in enumerate(_sd().query_devices())]


def pick_index(
    rows: Sequence[Mapping[str, Any]], prefix: str, kind: str, hostapi: int | None = None
) -> int | None:
    """PortAudio index of the first ``kind`` entry named ``prefix…``, on ``hostapi`` if any."""
    key = _CHANNELS[kind]
    matches = [
        (int(row.get("index", position)), row)
        for position, row in enumerate(rows)
        if str(row["name"]).startswith(prefix) and int(row[key]) > 0
    ]
    preferred = [match for match in matches if int(match[1]["hostapi"]) == hostapi]
    chosen = preferred or matches
    return chosen[0][0] if chosen else None


def _required(index: int | None, what: str) -> int:
    if index is None:
        raise LookupError(f"virtual cable {what} not found")
    return index


def legacy_input_index() -> int:
    """The PortAudio index an earlier Lianiq stored for "CABLE Output" (default host API)."""
    hostapi = int(_sd().default.hostapi)
    return _required(pick_index(devices(), CABLE_OUTPUT, "input", hostapi), "capture endpoint")


def wasapi_name(prefix: str, kind: str) -> str | None:
    """The WASAPI device name of the cable endpoint: the name the app shows and migrates to."""
    apis = list(_sd().query_hostapis())
    wasapi = next(
        (i for i, api in enumerate(apis) if "wasapi" in str(api["name"]).casefold()), None
    )
    rows = devices()
    index = pick_index([r for r in rows if r["hostapi"] == wasapi], prefix, kind, wasapi)
    return str(rows[index]["name"]) if index is not None else None


def phrase_wav(ctx: RunContext) -> Path:
    """The N-01 WAV from ``image.json``; ``ValueError`` unless its SHA-256 matches."""
    entry = ctx.image().get("test_phrase") or {}
    path = Path(str(entry.get("path") or ""))
    if not entry.get("sha256") or not path.is_file() or file_sha256(path) != entry["sha256"]:
        raise ValueError("test phrase missing or changed")
    return path


def read_wav(path: Path) -> tuple[int, Any]:
    """Sample rate and 16-bit frames (frames × channels) of a PCM WAV file."""
    import numpy

    with wave.open(str(path), "rb") as handle:
        if handle.getsampwidth() != 2:
            raise ValueError("test phrase is not 16-bit PCM")
        frames = handle.readframes(handle.getnframes())
        channels, rate = handle.getnchannels(), handle.getframerate()
    return rate, numpy.frombuffer(frames, dtype="<i2").reshape(-1, channels)


def play_into_cable(path: Path) -> None:
    """Play the WAV into "CABLE Input" and return when playback has finished."""
    sd = _sd()
    index = _required(
        pick_index(devices(), CABLE_INPUT, "output", int(sd.default.hostapi)), "render endpoint"
    )
    rate, frames = read_wav(path)
    sd.play(frames, rate, device=index, blocking=True)


def endpoint_names() -> list[str]:
    """Every audio endpoint name PortAudio or Windows lists (for masking), cable included."""
    names = {str(row["name"]) for row in devices()}
    for identity in _identities():
        names.update(identity.aliases)
    names.update(CABLE_NAMES)
    return sorted(name for name in names if name)


def cable_endpoint_ids() -> list[str]:
    """The cable's endpoint identifiers as the app stores them, and their bare registry key."""
    found: list[str] = []
    for identity in _identities():
        if any(alias.startswith(CABLE_NAMES) for alias in identity.aliases):
            found += [identity.endpoint_id, identity.endpoint_id.rsplit(":", 1)[-1]]
    return found


def _identities() -> list[Any]:
    from lianiq.audio.windows_endpoints import list_windows_endpoint_identities

    return list_windows_endpoint_identities()
