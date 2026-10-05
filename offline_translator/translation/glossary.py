from __future__ import annotations

import json
from pathlib import Path

from offline_translator.domain import Language


class Glossary:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._terms: dict[str, dict[str, str]] = {"de-zh": {}, "zh-de": {}}
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            for direction in self._terms:
                values = raw.get(direction, {})
                if isinstance(values, dict):
                    self._terms[direction] = {str(k): str(v) for k, v in values.items()}

    def apply(self, text: str, source: Language, target: Language) -> str:
        direction = f"{source.value}-{target.value}"
        result = text
        # Longest terms first prevents a short term from corrupting a longer one.
        for original, replacement in sorted(
            self._terms.get(direction, {}).items(), key=lambda pair: len(pair[0]), reverse=True
        ):
            result = result.replace(original, replacement)
        return result
