from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AudioDevice:
    index: int
    name: str
    inputs: int
    outputs: int


def list_audio_devices() -> list[AudioDevice]:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError("sounddevice is not installed") from exc
    result: list[AudioDevice] = []
    for index, raw in enumerate(sd.query_devices()):
        result.append(
            AudioDevice(
                index=index,
                name=str(raw["name"]),
                inputs=int(raw["max_input_channels"]),
                outputs=int(raw["max_output_channels"]),
            )
        )
    return result
