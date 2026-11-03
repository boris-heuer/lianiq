from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from lianiq.languages.registry import LanguageId


@dataclass(slots=True)
class ContextBuffer:
    """Recent source sentences keyed by source ``LanguageId``."""

    max_sentences: int = 5
    _items: deque[tuple[LanguageId, str, str]] = field(init=False)

    def __post_init__(self) -> None:
        self._items = deque(maxlen=max(0, self.max_sentences))

    def add(self, language: LanguageId, source: str, translation: str) -> None:
        if self.max_sentences:
            self._items.append((language, source, translation))

    def source_context(self, language: LanguageId) -> tuple[str, ...]:
        return tuple(source for lang, source, _ in self._items if lang == language)

    def clear(self) -> None:
        self._items.clear()
