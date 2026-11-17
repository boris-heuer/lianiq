"""Validation of the optional ``meeting.*`` settings keys (CAP-0177 contract.md §8).

The ``MeetingConfig`` fields and defaults live in ``config.py`` with the other blocks; this
module only checks them, so an invalid value fails the load with its key named.
"""

from __future__ import annotations

from typing import Any

# ``meeting.table_input_during_output`` values (``TableInputDuringOutput``, CAP-0177 §1).
TABLE_INPUT_MODES = frozenset({"mute", "open"})
USER_INPUT_POLICIES = frozenset({"follow_default", "explicit"})  # CAP-0168 ``DevicePolicy``
ENDPOINT_KEYS = (
    "table_capture_endpoint_id",
    "table_render_endpoint_id",
    "user_input_endpoint_id",
    "local_output_endpoint_id",
)
FLAG_KEYS = ("local_output_is_headset", "speak_local")
RANGES = {"guard_tail_ms": (0, 2_000), "max_playback_defer_ms": (1_000, 15_000)}


def validate_meeting_config(config: Any) -> None:
    """Raise ``ValueError`` naming the first ``meeting.*`` key of a wrong type or range."""

    def require(name: str, valid: bool, expected: str) -> None:
        if not valid:
            raise ValueError(f"meeting.{name} must be {expected}: {getattr(config, name)!r}")

    language = config.local_language
    require("local_language", isinstance(language, str) and bool(language), "a language ID")
    for name in ENDPOINT_KEYS:
        require(name, isinstance(getattr(config, name), str | None), "an endpoint ID or null")
    require("user_input_policy", config.user_input_policy in USER_INPUT_POLICIES, "a device policy")
    for name in FLAG_KEYS:
        require(name, isinstance(getattr(config, name), bool), "true or false")
    require(
        "table_input_during_output",
        config.table_input_during_output in TABLE_INPUT_MODES,
        "mute or open",
    )
    for name, (low, high) in RANGES.items():
        value = getattr(config, name)
        require(
            name, type(value) is int and low <= value <= high, f"an integer from {low} to {high}"
        )
