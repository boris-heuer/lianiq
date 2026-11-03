from __future__ import annotations

import sys
from types import SimpleNamespace

import numpy as np
import pytest

from lianiq.config import SpeechToTextConfig
from lianiq.languages import CapabilityMissingError, LanguageId, RequirementKind
from lianiq.stt.faster_whisper_engine import FasterWhisperEngine
from tests.languages.synthetic import QAA, QAB, synthetic_registry


class FakeWhisperModel:
    """Records ``transcribe`` calls and reports a scripted detected language."""

    def __init__(self, detected: str = "de", text: str = "Guten Tag", probability=0.97) -> None:
        self.detected = detected
        self.text = text
        self.probability = probability
        self.languages: list[str | None] = []

    def transcribe(self, samples, language=None, **_options):
        self.languages.append(language)
        info = SimpleNamespace(
            language=language or self.detected, language_probability=self.probability
        )
        return iter([SimpleNamespace(text=f" {self.text} ")]), info


def engine(tmp_path, model: FakeWhisperModel, languages=("de", "zh-Hans"), registry=None):
    config = SpeechToTextConfig(model_path=str(tmp_path), languages=list(languages), device="cpu")
    kwargs = {} if registry is None else {"registry": registry}
    result = FasterWhisperEngine(config, tmp_path, **kwargs)
    result._model = model
    return result


def audio() -> np.ndarray:
    return np.zeros(16_000, dtype=np.float32)


@pytest.mark.parametrize(("language_id", "whisper_code"), [("de", "de"), ("zh-Hans", "zh")])
def test_forced_language_id_maps_to_the_registry_whisper_code(
    tmp_path, language_id, whisper_code
) -> None:
    model = FakeWhisperModel()
    transcript = engine(tmp_path, model).transcribe(audio(), 16_000, LanguageId(language_id))

    assert model.languages == [whisper_code]
    assert transcript.language == language_id
    assert transcript.engine_language_code == whisper_code


@pytest.mark.parametrize(("whisper_code", "language_id"), [("de", "de"), ("zh", "zh-Hans")])
def test_detected_whisper_code_maps_back_to_the_registry_id(
    tmp_path, whisper_code, language_id
) -> None:
    model = FakeWhisperModel(detected=whisper_code, probability=0.81)
    transcript = engine(tmp_path, model).transcribe(audio(), 16_000)

    assert model.languages == [None]
    assert transcript.language == language_id
    assert transcript.probability == pytest.approx(0.81)
    assert transcript.engine_language_code == whisper_code


@pytest.mark.parametrize(
    ("whisper_code", "text", "expected"),
    [
        ("en", "您好", "en"),  # registered (planned): kept as detected, never re-guessed
        ("en", "Guten Tag", "en"),
        ("ja", "您好", None),  # unregistered: no script-based guess
        ("xx", "Guten Tag", None),
    ],
)
def test_no_script_based_guess_for_other_detected_languages(
    tmp_path, whisper_code, text, expected
) -> None:
    model = FakeWhisperModel(detected=whisper_code, text=text)
    transcript = engine(tmp_path, model).transcribe(audio(), 16_000)

    assert transcript.language == expected
    assert transcript.engine_language_code == whisper_code
    assert transcript.text == text


def test_forcing_an_unconfigured_recognition_language_raises(tmp_path) -> None:
    model = FakeWhisperModel()
    stt = engine(tmp_path, model, languages=("de",))

    with pytest.raises(CapabilityMissingError) as raised:
        stt.transcribe(audio(), 16_000, LanguageId("zh-Hans"))

    assert raised.value.requirement.kind is RequirementKind.RECOGNITION
    assert raised.value.requirement.subject == "zh-Hans"
    assert model.languages == []


def test_synthetic_registry_codes_are_used_for_synthetic_languages(tmp_path) -> None:
    model = FakeWhisperModel(detected="xb")
    stt = engine(tmp_path, model, languages=(QAA, QAB), registry=synthetic_registry())

    assert stt.transcribe(audio(), 16_000, QAA).language == QAA
    assert stt.transcribe(audio(), 16_000).language == QAB
    assert model.languages == ["xa", None]


def test_warm_up_runs_only_for_required_languages(tmp_path) -> None:
    model = FakeWhisperModel()
    stt = engine(tmp_path, model)

    stt.warm_up(())
    assert model.languages == []

    stt.warm_up((LanguageId("zh-Hans"),))
    assert model.languages == ["zh"]


def test_model_is_loaded_lazily_from_local_files_only(tmp_path, monkeypatch) -> None:
    loads = []

    class FakeLoader:
        def __init__(self, path, **options):
            loads.append((path, options))

        def transcribe(self, samples, language=None, **_options):
            return FakeWhisperModel().transcribe(samples, language)

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=FakeLoader))
    config = SpeechToTextConfig(model_path=str(tmp_path), device="cpu")
    stt = FasterWhisperEngine(config, tmp_path)

    assert loads == []
    stt.transcribe(audio(), 16_000, LanguageId("de"))
    stt.transcribe(audio(), 16_000)

    assert len(loads) == 1
    assert loads[0][1]["local_files_only"] is True
