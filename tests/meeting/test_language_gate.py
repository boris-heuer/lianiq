"""Per-input language gate (CAP-0177 contract §2).

AC-10 (Unit): the detection-pass text is used only for the expected language at or above
``languages.detection_min_probability``; everything else gets a pass forced to the expected
language. Unit halves of AC-08 (German on the table input) and AC-09 (Mandarin on the PO
microphone): the other pair language at or above the threshold is discarded.
"""

from __future__ import annotations

import pytest

from lianiq.domain import Transcript
from lianiq.languages import LanguageId
from lianiq.meeting.language_gate import GateDecision, LanguageGate
from tests.meeting.support import DE, DE_ZH, ZH

THRESHOLD = 0.7


def detection(language: LanguageId | None, probability: float, text: str = "x") -> Transcript:
    return Transcript(text=text, language=language, probability=probability, duration_seconds=1.0)


def table_gate() -> LanguageGate:
    return LanguageGate(expected=ZH, pair=DE_ZH, min_probability=THRESHOLD)


def user_gate() -> LanguageGate:
    return LanguageGate(expected=DE, pair=DE_ZH, min_probability=THRESHOLD)


def test_decision_values_are_the_contract_values():
    assert [decision.value for decision in GateDecision] == ["accept", "discard", "force"]


@pytest.mark.parametrize("probability", [THRESHOLD, 0.95, 1.0])
def test_ac10_expected_language_at_or_above_threshold_is_accepted(probability):
    assert table_gate().decide(detection(ZH, probability)) is GateDecision.ACCEPT
    assert user_gate().decide(detection(DE, probability)) is GateDecision.ACCEPT


@pytest.mark.parametrize("probability", [0.0, 0.5, 0.6999])
def test_ac10_expected_language_below_threshold_is_forced(probability):
    assert table_gate().decide(detection(ZH, probability)) is GateDecision.FORCE_EXPECTED
    assert user_gate().decide(detection(DE, probability)) is GateDecision.FORCE_EXPECTED


@pytest.mark.parametrize(
    "language", [LanguageId("en"), LanguageId("fr"), None], ids=["en", "fr", "unregistered"]
)
def test_ac10_language_outside_the_pair_is_forced_even_when_confident(language):
    assert table_gate().decide(detection(language, 0.99)) is GateDecision.FORCE_EXPECTED
    assert user_gate().decide(detection(language, 0.99)) is GateDecision.FORCE_EXPECTED


@pytest.mark.parametrize("probability", [THRESHOLD, 0.99])
def test_ac08_german_on_the_table_input_is_discarded(probability):
    assert table_gate().decide(detection(DE, probability)) is GateDecision.DISCARD


@pytest.mark.parametrize("probability", [THRESHOLD, 0.99])
def test_ac09_mandarin_on_the_user_microphone_is_discarded(probability):
    assert user_gate().decide(detection(ZH, probability)) is GateDecision.DISCARD


def test_other_pair_language_below_threshold_is_forced_not_discarded():
    assert table_gate().decide(detection(DE, 0.69)) is GateDecision.FORCE_EXPECTED
    assert user_gate().decide(detection(ZH, 0.69)) is GateDecision.FORCE_EXPECTED


def test_decision_does_not_depend_on_the_text():
    assert table_gate().decide(detection(ZH, 0.9, text="")) is GateDecision.ACCEPT
    assert table_gate().decide(detection(DE, 0.9, text="")) is GateDecision.DISCARD


def test_threshold_follows_the_configured_value():
    strict = LanguageGate(expected=ZH, pair=DE_ZH, min_probability=0.9)
    assert strict.decide(detection(ZH, 0.85)) is GateDecision.FORCE_EXPECTED
    assert strict.decide(detection(DE, 0.85)) is GateDecision.FORCE_EXPECTED
    lenient = LanguageGate(expected=ZH, pair=DE_ZH, min_probability=0.0)
    assert lenient.decide(detection(DE, 0.0)) is GateDecision.DISCARD


def test_gate_exposes_its_expected_language_and_threshold():
    gate = table_gate()
    assert gate.expected == ZH
    assert gate.min_probability == THRESHOLD


def test_expected_language_must_be_a_pair_member():
    with pytest.raises(ValueError):
        LanguageGate(expected=LanguageId("en"), pair=DE_ZH, min_probability=THRESHOLD)


@pytest.mark.parametrize("probability", [-0.01, 1.01])
def test_threshold_must_be_a_probability(probability):
    with pytest.raises(ValueError):
        LanguageGate(expected=ZH, pair=DE_ZH, min_probability=probability)
