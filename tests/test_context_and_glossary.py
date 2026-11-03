from __future__ import annotations

import json
from pathlib import Path

from lianiq.config import PROJECT_ROOT
from lianiq.languages import DirectedEdge, LanguageId
from lianiq.translation.context import ContextBuffer
from lianiq.translation.glossary import Glossary
from tests.languages.synthetic import QAA, QAB

DE = LanguageId("de")
ZH = LanguageId("zh-Hans")
DE_ZH = DirectedEdge(DE, ZH)
ZH_DE = DirectedEdge(ZH, DE)


def write_glossary(tmp_path: Path, content: dict) -> Glossary:
    path = tmp_path / "glossary.json"
    path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    return Glossary(path)


def test_context_is_bounded_and_filtered_by_language_id() -> None:
    context = ContextBuffer(2)
    context.add(DE, "eins", "一")
    context.add(ZH, "二", "zwei")
    context.add(DE, "drei", "三")
    assert context.source_context(DE) == ("drei",)
    assert context.source_context(ZH) == ("二",)
    assert context.source_context(QAA) == ()
    context.clear()
    assert context.source_context(DE) == ()


def test_glossary_prefers_long_terms(tmp_path: Path) -> None:
    glossary = write_glossary(tmp_path, {"de>zh-Hans": {"AI PC": "人工智能电脑", "PC": "电脑"}})
    assert glossary.apply("AI PC and PC", DE_ZH) == "人工智能电脑 and 电脑"


def test_ac17_legacy_de_zh_terms_apply_only_to_their_own_edge(tmp_path: Path) -> None:
    glossary = write_glossary(tmp_path, {"de-zh": {"Termin": "预约"}})

    assert glossary.apply("Termin", DE_ZH) == "预约"
    assert glossary.apply("Termin", ZH_DE) == "Termin"
    assert glossary.apply("Termin", DirectedEdge(QAA, QAB)) == "Termin"
    assert glossary.apply("Termin", DirectedEdge(QAB, QAA)) == "Termin"
    assert dict(glossary.terms(DE_ZH)) == {"Termin": "预约"}
    assert dict(glossary.terms(ZH_DE)) == {}


def test_legacy_zh_de_key_maps_to_the_reverse_edge_only(tmp_path: Path) -> None:
    glossary = write_glossary(tmp_path, {"zh-de": {"会议": "Besprechung"}})

    assert glossary.apply("会议", ZH_DE) == "Besprechung"
    assert glossary.apply("会议", DE_ZH) == "会议"


def test_edge_keys_override_legacy_keys_and_unknown_keys_are_ignored(tmp_path: Path) -> None:
    glossary = write_glossary(
        tmp_path,
        {
            "de>zh-Hans": {"PC": "个人电脑"},
            "de-zh": {"PC": "电脑", "Termin": "预约"},
            "qaa>qab": {"PC": "synthetic"},
            "not-an-edge": {"PC": "ignored"},
            "de>de": {"PC": "ignored"},
        },
    )

    assert dict(glossary.terms(DE_ZH)) == {"PC": "个人电脑", "Termin": "预约"}
    assert glossary.apply("PC", DirectedEdge(QAA, QAB)) == "synthetic"
    assert glossary.apply("PC", ZH_DE) == "PC"


def test_missing_glossary_file_applies_no_terms(tmp_path: Path) -> None:
    assert Glossary(tmp_path / "absent.json").apply("PC", DE_ZH) == "PC"


def test_shipped_glossary_is_keyed_by_directed_edge() -> None:
    raw = json.loads((PROJECT_ROOT / "config" / "glossary.json").read_text(encoding="utf-8"))

    assert {DirectedEdge.from_key(key) for key in raw} == {DE_ZH, ZH_DE}
