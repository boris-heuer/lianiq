from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from lianiq.domain import Language


@dataclass(slots=True)
class ContextBuffer:
    max_sentences: int = 5
    _items: deque[tuple[Language, str, str]] = field(init=False)

    def __post_init__(self) -> None:
        self._items = deque(maxlen=max(0, self.max_sentences))

    def add(self, language: Language, source: str, translation: str) -> None:
        if self.max_sentences:
            self._items.append((language, source, translation))

    def source_context(self, language: Language) -> tuple[str, ...]:
        return tuple(source for lang, source, _ in self._items if lang is language)

    def clear(self) -> None:
        self._items.clear()
