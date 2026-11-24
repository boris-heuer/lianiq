"""The virtual cable for E-11, E-03 and the cable-measured rows (CAP-0174 contract §5, §6).

VB-Cable has two endpoints: the app records from "CABLE Output" (capture) and the row plays
the N-01 test phrase into "CABLE Input" (render). PortAudio lists each endpoint once per host
API; ``pick_index`` prefers the given host API (the default one for playback and for the
legacy index, WASAPI for the name the app shows) and falls back to the first entry.

``sounddevice`` (app lock) and numpy are imported lazily; the endpoint identities come from
the app's own read-only registry reader. No function returns an endpoint name or identifier
into the evidence: callers compare them or hand them to the redaction scan and the mask.
``record_cable``, ``CableRecorder`` and ``speech_span`` measure what the app plays into the
cable (spec §2.1.5): the samples stay in memory and only durations reach the evidence.
"""

from __future__ import annotations

import wave
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

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


# Cable capture (spec §2.1.5): "CABLE Output" carries what the app plays into "CABLE Input".
# Samples stay in memory; rows store durations only, never PCM.
FRAME_S = 0.020
SPEECH_RMS = 0.01  # about -40 dBFS on float samples in [-1, 1]


def _capture_device() -> tuple[int, int]:
    sd = _sd()
    rows = devices()
    index = _required(
        pick_index(rows, CABLE_OUTPUT, "input", int(sd.default.hostapi)), "capture endpoint"
    )
    return index, int(float(rows[index]["default_samplerate"]))


def record_cable(seconds: float) -> tuple[int, Any]:
    """Record "CABLE Output" (shared mode) for ``seconds``: (rate, float32 mono samples)."""
    sd = _sd()
    index, rate = _capture_device()
    frames = sd.rec(int(seconds * rate), samplerate=rate, channels=1, device=index, blocking=True)
    return rate, frames.reshape(-1)


def speech_span(
    samples: Any, rate: int, threshold: float = SPEECH_RMS
) -> tuple[float, float] | None:
    """(first, last) seconds of the 20 ms frames whose RMS exceeds ``threshold``, else
    ``None``; int16 samples are scaled to [-1, 1] first."""
    import numpy

    values = numpy.asarray(samples).reshape(-1)
    if values.dtype.kind in "iu":
        values = values.astype("float32") / 32768.0
    size = max(1, int(rate * FRAME_S))
    count = values.size // size
    if count == 0:
        return None
    frames = values[: count * size].astype("float64").reshape(count, size)
    loud = numpy.flatnonzero(numpy.sqrt(numpy.mean(frames * frames, axis=1)) > threshold)
    if loud.size == 0:
        return None
    return float(loud[0] * size / rate), float((loud[-1] + 1) * size / rate)


class CableRecorder:
    """Background recording of "CABLE Output": ``start``, then ``mark`` (seconds into the
    recording, for example at a key press), then ``stop`` → (rate, samples)."""

    def __init__(self) -> None:
        import threading

        self._lock = threading.Lock()
        self._chunks: list[Any] = []
        self._frames = 0
        self._stream: Any = None
        self.rate = 0

    def _callback(self, data: Any, frames: int, _time: Any, _status: Any) -> None:
        with self._lock:
            self._chunks.append(data[:, 0].copy())
            self._frames += frames

    def start(self) -> Self:
        index, self.rate = _capture_device()
        stream = _sd().InputStream(
            samplerate=self.rate, channels=1, device=index, callback=self._callback
        )
        stream.start()
        self._stream = stream
        return self

    def mark(self) -> float:
        """Seconds of audio received so far (the timeline of the samples ``stop`` returns)."""
        with self._lock:
            return self._frames / self.rate if self.rate else 0.0

    def stop(self) -> tuple[int, Any]:
        import numpy

        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        with self._lock:
            chunks, self._chunks = self._chunks, []
        samples = numpy.concatenate(chunks) if chunks else numpy.zeros(0, dtype="float32")
        return self.rate, samples

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(self, *_exc: object) -> None:
        self.stop()
