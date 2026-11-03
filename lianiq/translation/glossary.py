from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from lianiq.config_migration import LEGACY_GLOSSARY_EDGES
from lianiq.languages.capabilities import DirectedEdge


class Glossary:
    """Glossary terms per directed edge; terms apply only to their own edge.

    ``glossary.json`` is keyed by edge (``"de>zh-Hans"``). Legacy direction keys
    (``LEGACY_GLOSSARY_EDGES``) map to their edge on load; an edge key in the same file
    wins over a legacy key for the same term. Other keys are ignored.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._terms: dict[DirectedEdge, dict[str, str]] = {}
        if not path.exists():
            return
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return
        # Legacy keys first, so edge keys override them.
        for key in sorted(raw, key=lambda item: item not in LEGACY_GLOSSARY_EDGES):
            edge = _edge_for_key(key)
            values = raw[key]
            if edge is None or not isinstance(values, dict):
                continue
            self._terms.setdefault(edge, {}).update(
                {str(original): str(replacement) for original, replacement in values.items()}
            )

    def terms(self, edge: DirectedEdge) -> Mapping[str, str]:
        return dict(self._terms.get(edge, {}))

    def apply(self, text: str, edge: DirectedEdge) -> str:
        result = text
        # Longest terms first prevents a short term from corrupting a longer one.
        for original, replacement in sorted(
            self._terms.get(edge, {}).items(), key=lambda pair: len(pair[0]), reverse=True
        ):
            result = result.replace(original, replacement)
        return result


def _edge_for_key(key: str) -> DirectedEdge | None:
    try:
        return DirectedEdge.from_key(LEGACY_GLOSSARY_EDGES.get(key, key))
    except (LookupError, ValueError):
        return None
