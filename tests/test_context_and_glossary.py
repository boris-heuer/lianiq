from __future__ import annotations

import json
from pathlib import Path

from offline_translator.domain import Language
from offline_translator.translation.context import ContextBuffer
from offline_translator.translation.glossary import Glossary


def test_context_is_bounded_and_filtered_by_language() -> None:
    context = ContextBuffer(2)
    context.add(Language.GERMAN, "eins", "一")
    context.add(Language.MANDARIN, "二", "zwei")
    context.add(Language.GERMAN, "drei", "三")
    assert context.source_context(Language.GERMAN) == ("drei",)
    assert context.source_context(Language.MANDARIN) == ("二",)


def test_glossary_prefers_long_terms(tmp_path: Path) -> None:
    path = tmp_path / "glossary.json"
    path.write_text(
        json.dumps({"de-zh": {"AI PC": "人工智能电脑", "PC": "电脑"}}),
        encoding="utf-8",
    )
    glossary = Glossary(path)
    assert (
        glossary.apply("AI PC and PC", Language.GERMAN, Language.MANDARIN)
        == "人工智能电脑 and 电脑"
    )
