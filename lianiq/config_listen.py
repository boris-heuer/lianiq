"""The optional ``listen.*`` settings block (CAP-0170 spec §4.2, schema v2 additive).

Language IDs and the microphone are stored by ID only; display names and transcript text
are never stored. An unknown language ID falls back to the default when the page is built.
"""

from __future__ import annotations

from dataclasses import dataclass

INPUT_POLICIES = frozenset({"follow_default", "explicit"})  # CAP-0168 ``DevicePolicy``


@dataclass(slots=True)
class ListenConfig:
    source_language: str | None = None  # None: ``languages.pair[0]``
    target_language: str | None = None  # None: ``languages.pair[1]``
    input_policy: str = "follow_default"
    input_endpoint_id: str | None = None  # used iff ``input_policy`` is explicit

    def __post_init__(self) -> None:
        def require(name: str, valid: bool, expected: str) -> None:
            if not valid:
                raise ValueError(f"listen.{name} must be {expected}: {getattr(self, name)!r}")

        for name in ("source_language", "target_language"):
            value = getattr(self, name)
            require(name, value is None or (isinstance(value, str) and bool(value)), "an ID")
        require("input_policy", self.input_policy in INPUT_POLICIES, "a device policy")
        require(
            "input_endpoint_id",
            isinstance(self.input_endpoint_id, str | None),
            "an endpoint ID or null",
        )
