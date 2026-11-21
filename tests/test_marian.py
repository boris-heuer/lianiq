from __future__ import annotations

import contextlib
import json
import sys
import threading
import time
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

        self.inputs: list[str] = []

    def __call__(self, text, **options):
        if options.get("truncation") is False:  # token_count: one token per word plus EOS
            return {"input_ids": list(range(len(text.split()) + 1))}
        self.inputs.append(text)
        return {"input_ids": FakeTensor()}

    def batch_decode(self, _tokens, skip_special_tokens=True):
        return [self.decoded]


class FakeModel:
    """Records the largest number of overlapping ``generate`` calls (CAP-0172 AC-35)."""

    delay = 0.0
    active = 0
    overlap = 0
    guard = threading.Lock()

    def generate(self, **_options):
        with FakeModel.guard:
            FakeModel.active += 1
            FakeModel.overlap = max(FakeModel.overlap, FakeModel.active)
        time.sleep(FakeModel.delay)
        with FakeModel.guard:
            FakeModel.active -= 1
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


# CAP-0172 WI-01: the Marian lock and ``token_count`` (contract.md §6), with fakes only.


def test_token_count_measures_the_model_input_of_the_edge(tmp_path, fake_runtime) -> None:
    marian = translator(tmp_path, [DE_ZH])

    assert marian.token_count("drei kurze Wörter", DE_ZH) == 4
    with pytest.raises(CapabilityMissingError):
        marian.token_count("x", ZH_DE)


def test_token_count_drives_the_text_segment_budget(tmp_path, fake_runtime) -> None:
    from lianiq.text_translation.jobs import TranslationJobs
    from lianiq.text_translation.segments import SEGMENT_TOKEN_BUDGET
    from lianiq.text_translation.state import DraftState
    from tests.text_translation._text_helpers import GuiThread

    marian = translator(tmp_path, [DE_ZH])
    gui, results = GuiThread(), []
    jobs = TranslationJobs(lambda: marian, gui.post)
    request = DraftState(DE, ZH, " ".join(f"w{i}" for i in range(400)) + ".").request()
    jobs.start(request, results.append, lambda *_: None, lambda *_: None)
    gui.pump(lambda: bool(results))
    jobs.shutdown()

    inputs = marian._loaded[DE_ZH][0].inputs
    assert len(inputs) > 3
    assert all(marian.token_count(text, DE_ZH) <= SEGMENT_TOKEN_BUDGET for text in inputs)


def test_ac15_text_jobs_apply_the_glossary_of_the_selected_edge_only(
    tmp_path, fake_runtime
) -> None:
    from lianiq.text_translation.jobs import TranslationJobs
    from lianiq.text_translation.state import DraftState
    from tests.text_translation._text_helpers import GuiThread

    marian = translator(tmp_path, [DE_ZH, ZH_DE], {"de>zh-Hans": {"AI PC": "人工智能电脑"}})
    gui, results = GuiThread(), []
    jobs = TranslationJobs(lambda: marian, gui.post)
    for source, target in ((DE, ZH), (ZH, DE)):
        jobs.start(DraftState(source, target, "Ein Satz.").request(), results.append, print, print)
        count = len(results) + 1
        gui.pump(lambda count=count: len(results) == count)
    jobs.shutdown()

    assert [result.text for result in results] == ["人工智能电脑", "AI PC"]


def test_ac35_text_and_conversation_translations_never_overlap(
    tmp_path, fake_runtime, monkeypatch
) -> None:
    from lianiq.text_translation.jobs import TranslationJobs
    from lianiq.text_translation.state import DraftState
    from tests.text_translation._text_helpers import GuiThread

    monkeypatch.setattr(FakeModel, "delay", 0.002)
    monkeypatch.setattr(FakeModel, "active", 0)
    monkeypatch.setattr(FakeModel, "overlap", 0)
    marian = translator(tmp_path, [DE_ZH, ZH_DE])
    gui, results = GuiThread(), []
    jobs = TranslationJobs(lambda: marian, gui.post)
    text = " ".join(f"Satz {i} endet hier." for i in range(40))
    turns: list[str] = []

    def conversation() -> None:  # spy Conversation turns on their own thread
        for _ in range(40):
            turns.append(marian.translate("你好", ZH_DE))

    turn_thread = threading.Thread(target=conversation)
    jobs.start(DraftState(DE, ZH, text).request(), results.append, print, print)
    turn_thread.start()
    gui.pump(lambda: bool(results), timeout=20)
    turn_thread.join(20)
    jobs.shutdown()

    assert not turn_thread.is_alive() and len(turns) == 40  # both complete, no deadlock
    assert len(results) == 1 and len(results[0].segments) == 40
    assert FakeModel.overlap == 1
