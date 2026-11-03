from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from lianiq.languages import CapabilityMissingError, DirectedEdge, LanguageId, RequirementKind
from lianiq.translation.glossary import Glossary
from lianiq.translation.marian_engine import MarianTranslator

DE = LanguageId("de")
ZH = LanguageId("zh-Hans")
DE_ZH = DirectedEdge(DE, ZH)
ZH_DE = DirectedEdge(ZH, DE)


class FakeTensor:
    def to(self, _device):
        return self


class FakeTokenizer:
    def __init__(self, decoded: str) -> None:
        self.decoded = decoded

    def __call__(self, text, **_options):
        return {"input_ids": FakeTensor()}

    def batch_decode(self, _tokens, skip_special_tokens=True):
        return [self.decoded]


class FakeModel:
    def generate(self, **_options):
        return [[0]]


@pytest.fixture
def fake_runtime(monkeypatch):
    """Fake ``torch``/``transformers`` that record every model load."""
    loads: list[tuple[str, Path, dict]] = []

    def loader(kind: str, result):
        def from_pretrained(path, **options):
            loads.append((kind, Path(path), options))
            return result

        return SimpleNamespace(from_pretrained=from_pretrained)

    model = SimpleNamespace(
        to=lambda _device: None, eval=lambda: None, generate=FakeModel().generate
    )
    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(
            AutoTokenizer=loader("tokenizer", FakeTokenizer("AI PC")),
            AutoModelForSeq2SeqLM=loader("model", model),
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(
            set_num_threads=lambda _n: None,
            inference_mode=contextlib.nullcontext,
            cuda=SimpleNamespace(is_available=lambda: False),
        ),
    )
    return loads


def translator(tmp_path: Path, edges, glossary_terms=None) -> MarianTranslator:
    glossary_path = tmp_path / "glossary.json"
    glossary_path.write_text(json.dumps(glossary_terms or {}, ensure_ascii=False), "utf-8")
    paths = {}
    for edge in edges:
        path = tmp_path / f"mt-{edge.source}-{edge.target}"
        path.mkdir()
        paths[edge] = path
    return MarianTranslator(paths, Glossary(glossary_path), device="cpu")


def test_unconfigured_edge_raises_and_the_reverse_edge_is_never_used(
    tmp_path, fake_runtime
) -> None:
    marian = translator(tmp_path, [DE_ZH])

    with pytest.raises(CapabilityMissingError) as raised:
        marian.translate("你好", ZH_DE)

    assert raised.value.requirement.kind is RequirementKind.TRANSLATION
    assert raised.value.requirement.subject == "zh-Hans>de"
    assert fake_runtime == []


def test_edges_load_lazily_per_edge_from_local_files_only(tmp_path, fake_runtime) -> None:
    marian = translator(tmp_path, [DE_ZH, ZH_DE])
    assert fake_runtime == []

    marian.warm_up((DE_ZH,))

    assert [(kind, path.name) for kind, path, _options in fake_runtime] == [
        ("tokenizer", "mt-de-zh-Hans"),
        ("model", "mt-de-zh-Hans"),
    ]
    assert all(options == {"local_files_only": True} for _kind, _path, options in fake_runtime)

    marian.warm_up((DE_ZH,))
    marian.translate("x", DE_ZH)
    assert len(fake_runtime) == 2  # cached per edge

    marian.translate("x", ZH_DE)
    assert [path.name for _kind, path, _options in fake_runtime[2:]] == ["mt-zh-Hans-de"] * 2


def test_ac17_translation_applies_legacy_glossary_terms_only_on_their_edge(
    tmp_path, fake_runtime
) -> None:
    marian = translator(tmp_path, [DE_ZH, ZH_DE], {"de-zh": {"AI PC": "人工智能电脑"}})

    assert marian.translate("AI PC", DE_ZH) == "人工智能电脑"
    assert marian.translate("AI PC", ZH_DE) == "AI PC"
