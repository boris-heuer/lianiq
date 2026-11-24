"""The Meeting *Your language* selector with English ↔ Mandarin (CAP-0181 AC-09).

pytest-qt style offscreen UI tests over spy adapters (``_meeting_window.py``) and the English
packs of ``test_main_window_english_pair.py``.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lianiq.languages import LanguageId
from tests._spy_window import spies  # noqa: F401
from tests.ui._meeting_window import assign_table, build_meeting_window, end_and_wait
from tests.ui._meeting_window import start_meeting as start
from tests.ui.test_main_window_english_pair import EN_PAIR, with_english

EN, ZH = LanguageId("en"), LanguageId("zh-Hans")
NAMES = ["English", "Mandarin (Simplified)"]


def english_meeting(tmp_path, monkeypatch, request, *, local: str = "de"):
    english = with_english()

    def configure(config, root) -> None:
        english(config, root)
        config.languages.pair = [EN, ZH]
        config.meeting.local_language = local

    window = build_meeting_window(tmp_path, monkeypatch, configure=configure)
    request.addfinalizer(window.close)
    request.addfinalizer(lambda: end_and_wait(window))
    return window


def choose_local(window, index: int) -> None:
    combo = window.meeting.local_language_combo
    combo.setCurrentIndex(index)
    combo.activated.emit(index)


def test_ac09_saved_german_opens_as_english_and_the_table_reads_mandarin(
    tmp_path,
    monkeypatch,
    request,
    spies,  # noqa: F811
) -> None:
    meeting = english_meeting(tmp_path, monkeypatch, request).meeting
    combo = meeting.local_language_combo

    assert meeting.pair_combo.currentText() == EN_PAIR
    assert combo.accessibleName() == "Your language"
    assert [combo.itemText(i) for i in range(combo.count())] == NAMES
    assert [combo.itemData(i) for i in range(combo.count())] == [EN, ZH]
    assert combo.currentText() == "English" and combo.isEnabled()
    assert meeting.table_language_label.text() == "Table language: Mandarin (Simplified)"
    assert meeting.table_language_label.accessibleName() == meeting.table_language_label.text()
    assert meeting.session().local_language == EN
    assert meeting.speak_local_checkbox.text() == "Speak English for me"
    assert meeting.config.meeting.local_language == "de"  # kept until the PO chooses


def test_ac09_choosing_mandarin_swaps_both_and_saves_it(
    tmp_path,
    monkeypatch,
    request,
    spies,  # noqa: F811
) -> None:
    window = english_meeting(tmp_path, monkeypatch, request)
    meeting = window.meeting

    choose_local(window, 1)

    assert meeting.local_language_combo.currentText() == "Mandarin (Simplified)"
    assert meeting.table_language_label.text() == "Table language: English"
    assert meeting.speak_local_checkbox.text() == "Speak Mandarin (Simplified) for me"
    assert meeting.session().local_language == ZH
    window.config.save(tmp_path / "saved.json")
    saved = json.loads((tmp_path / "saved.json").read_text(encoding="utf-8"))
    assert saved["meeting"]["local_language"] == "zh-Hans"


def test_ac09_the_selector_follows_the_pair_and_is_locked_while_the_meeting_runs(
    tmp_path,
    monkeypatch,
    request,
    spies,  # noqa: F811
) -> None:
    window = english_meeting(tmp_path, monkeypatch, request)
    meeting = window.meeting
    combo = meeting.local_language_combo

    window.pair_combo.setCurrentText("German ↔ Mandarin (Simplified)")
    assert combo.currentText() == "German"  # the saved language is a member again
    window.pair_combo.setCurrentText(EN_PAIR)
    assert combo.currentText() == "English"
    assign_table(window)
    start(window)
    assert not combo.isEnabled()
    assert window.meeting_factory.calls[-1][0].local_language == EN
    end_and_wait(window)
    assert combo.isEnabled()


def test_ac09_the_selector_is_disabled_without_a_ready_pair(
    tmp_path,
    monkeypatch,
    request,
    spies,  # noqa: F811
) -> None:
    window = build_meeting_window(tmp_path, monkeypatch, provisioned=False)
    request.addfinalizer(window.close)

    assert window.current_pair() is None
    assert not window.meeting.local_language_combo.isEnabled()
