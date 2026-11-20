"""Pack job values (CAP-0171 contract.md §5 ``JobPhase``, §6 ``JobView``). Qt-free.

``JobPhase`` lives here rather than in ``installer.py`` so that ``state.py`` needs no
installer import; the job runner and its listener are added by a later work item.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class JobPhase(StrEnum):
    TRANSFER = "transfer"
    CHECK = "check"
    SWAP = "swap"


@dataclass(frozen=True, slots=True)
class JobView:
    pack_id: str
    operation: Literal["install", "update", "remove"]
    phase: JobPhase
    done: int  # bytes or files done in this phase
    total: int
