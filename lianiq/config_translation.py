"""Translation edge settings and the recognition list merge (CAP-0181 spec §3.2).

Qt-free. ``TranslationEdgeConfig`` is re-exported from ``lianiq.config``; the repository
default edges stay in ``config.py`` (``_default_edges``).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

# A Marian target-language token such as ``>>cmn_Hans<<`` (spec §3.3).
_TARGET_PREFIX = re.compile(r">>[A-Za-z0-9_]+<<")


@dataclass(slots=True)
class TranslationEdgeConfig:
    """One directed translation edge; its reverse edge is configured separately.

    ``target_prefix`` is prepended (plus one space) to each source text of a multi-target
    Marian model; empty for single-target models.
    """

    model_path: str
    target_prefix: str = ""

    def __post_init__(self) -> None:
        if self.target_prefix and not _TARGET_PREFIX.fullmatch(self.target_prefix):
            raise ValueError(
                f"translation edge target_prefix must be >>id<<: {self.target_prefix!r}"
            )


def edges_from_mapping(edges: Mapping[str, Any]) -> dict[str, TranslationEdgeConfig]:
    """Build and check ``translation.edges`` keyed ``"<source>><target>"``."""
    result = {
        key: edge if isinstance(edge, TranslationEdgeConfig) else TranslationEdgeConfig(**edge)
        for key, edge in edges.items()
    }
    for key in result:
        source, separator, target = key.partition(">")
        if not separator or not source or not target or ">" in target:
            raise ValueError(f"translation.edges key must be '<source>><target>': {key!r}")
    return result


def union_languages(saved: Iterable[str], defaults: Iterable[str]) -> list[str]:
    """Saved order first, then each default language the saved list lacks."""
    result = list(saved)
    return result + [language for language in defaults if language not in result]
