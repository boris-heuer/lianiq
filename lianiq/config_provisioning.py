"""The ``provisioning`` settings section (CAP-0171 contract.md §9), additive in schema v2.

``first_run`` records whether the first-run setup assistant is still pending; ``usages`` and
``languages`` keep the assistant's last choices. An absent section loads as the defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

FIRST_RUN_VALUES = frozenset({"pending", "completed", "skipped"})
_LIST_KEYS = ("usages", "languages")


@dataclass(frozen=True, slots=True)
class ProvisioningConfig:
    first_run: Literal["pending", "completed", "skipped"] = "pending"
    usages: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.first_run not in FIRST_RUN_VALUES:
            raise ValueError(f"Unsupported provisioning.first_run: {self.first_run!r}")
        for name in _LIST_KEYS:
            if not all(isinstance(item, str) for item in getattr(self, name)):
                raise ValueError(f"provisioning.{name} must list strings only")


def provisioning_from_mapping(raw: object) -> ProvisioningConfig:
    """Build the section; a non-object section or a non-list ``usages`` or ``languages``
    raises ``ValueError``."""
    if not isinstance(raw, dict):
        raise ValueError(f"provisioning must be an object: {raw!r}")  # noqa: TRY004 - C §9
    values: dict[str, Any] = dict(raw)
    for name in _LIST_KEYS:
        if name in values:
            if not isinstance(values[name], list):
                raise ValueError(f"provisioning.{name} must be a list: {values[name]!r}")
            values[name] = tuple(values[name])
    return ProvisioningConfig(**values)
