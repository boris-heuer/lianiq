"""CAP-0171 WI-06: the first-run setup assistant (spec §2.2.1; C §7, §9; offscreen).

AC-01..AC-06, AC-21 (socket guard) and AC-29; the launch rule (AC-01, AC-32 and the upgrade
half of AC-31) is in ``test_setup_assistant_launch``. The window
loads the shaped built-in catalog of ``_language_packs_helpers`` with the fake devices of
``_spy_window``; ``network`` records every socket attempt.
"""

from __future__ import annotations

import json

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import lianiq.config as config_module
import lianiq.ui.main_window as main_window_module
from lianiq import app
from lianiq.languages import BUILTIN_REGISTRY
from lianiq.languages.requirements import Requirement, RequirementKind
from lianiq.packs.usage import ReviewRow, ReviewStatus, is_device_row
from lianiq.ui import device_tests as device_tests_module
from lianiq.ui import strings
from lianiq.ui.setup_assistant import open_setup_assistant
from lianiq.ui.setup_assistant import step_audio as audio_module
from lianiq.ui.setup_assistant.assistant import AUDIO, LANGUAGES, REVIEW, USAGE
from lianiq.ui.setup_assistant.step_languages import LanguagesStep
from lianiq.ui.setup_assistant.step_usage import UsageStep
from lianiq.ui.workspaces import pack_details_dialog as dialog_module
from tests._spy_window import spies  # noqa: F401
from tests.languages.synthetic import synthetic_registry
from tests.packs.conftest import network_attempts  # noqa: F401
from tests.ui._language_packs_helpers import (  # noqa: F401 - the fixtures are imported
    MT,
    STT,
    open_page,
    pack_folder,
    packs_network,
    packs_shaped,
    packs_window,
    wait_until,
)

MT_BACK = "mt-zh-hans-de"
APPLICATION = QApplication.instance() or QApplication([])  # the step widgets need one


def texts(widget) -> list[str]:
    return [widget.item(row).text() for row in range(widget.count())]


def enabled(widget) -> list[bool]:
    return [
        bool(widget.item(row).flags() & Qt.ItemFlag.ItemIsEnabled) for row in range(widget.count())
    ]


def to_step(assistant, index: int) -> None:
    while assistant.pages.currentIndex() < index:
        assistant.next_button.click()
    assert assistant.pages.currentIndex() == index


def reviewed(assistant):
    to_step(assistant, REVIEW)
    assert wait_until(lambda: assistant.review.review is not None)
    return assistant.review


def test_ac03_usage_step_offers_enabled_and_experimental_usages_only() -> None:
    step = UsageStep()
    boxes = {key: (box.text(), box.isEnabled(), box.isChecked()) for key, box in step.boxes.items()}
    assert boxes == {
        "conversation": ("Conversation", True, True),
        "call-bridge": ("Call Bridge (Experimental)", True, False),
        "meeting": ("Meeting dual-mic", True, False),
        "text-translation": ("Text translation", True, False),
        "listen-and-translate": ("Listen & translate", True, False),
    }
    step.boxes["conversation"].setChecked(False)
    assert not step.complete()  # Next needs one ticked usage
    picked = UsageStep(("meeting", "text-translation")).selected()
    assert [p.id for p in picked] == ["meeting", "text-translation"]


def test_ac04_languages_follow_the_registry_with_planned_disabled() -> None:
    step = LanguagesStep(BUILTIN_REGISTRY)
    first = step.lists[0]
    assert texts(first) == [
        "German",
        "Mandarin (Simplified)",
        "English — Planned",
        "Spanish — Planned",
        "French — Planned",
    ]
    assert enabled(first) == [True, True, False, False, False]
    assert step.pair() == BUILTIN_REGISTRY.pair("de", "zh-Hans")  # preselected
    step.lists[1].setCurrentRow(0)
    assert not step.complete()  # the same language twice
    synthetic = LanguagesStep(synthetic_registry())
    assert texts(synthetic.lists[1]) == ["Synthetic A", "Synthetic B"]
    assert synthetic.complete()


def test_review_rows_tell_devices_apart_by_requirement_kind() -> None:
    uncovered = ReviewRow(
        None, (Requirement(RequirementKind.VOICE, "qaa"),), ReviewStatus.NOT_INSTALLED, True, ()
    )
    device = ReviewRow(
        None, (Requirement(RequirementKind.MICROPHONE),), ReviewStatus.READY, False, ("A",)
    )
    assert (is_device_row(uncovered), is_device_row(device)) == (False, True)


def test_ac06_audio_check_lists_ticked_roles_and_meters_a_synthetic_microphone(
    window, monkeypatch
) -> None:
    monkeypatch.setattr(device_tests_module.MicrophoneCapture, "start", lambda self: None)
    monkeypatch.setattr(device_tests_module.MicrophoneCapture, "stop", lambda self: None)
    assistant = open_setup_assistant(window)
    assistant.usage.boxes["meeting"].setChecked(True)
    to_step(assistant, AUDIO)
    lines = [label.text() for label in assistant.audio.role_labels]
    assert lines[:2] == ["Microphone: Test microphone", "Speakers: Test speakers"]
    assert len(lines) == 5  # Conversation and the three Meeting roles; no Call Bridge
    assert all(": " in line for line in lines[2:])
    assistant.audio.test_mic_button.click()
    assert window.device_setup.testing
    window.device_setup.test_level.emit(0.5)
    assert assistant.audio.meter.value() == 50
    window.device_setup.stop_microphone_test()
    assistant.back_button.click()
    assistant.back_button.click()
    assistant.usage.boxes["meeting"].setChecked(False)
    window.fake_devices.set()  # no devices left: missing devices never block Next
    window.device_setup.refresh()
    to_step(assistant, AUDIO)
    assert [label.text() for label in assistant.audio.role_labels] == [
        "Microphone: Not found",
        "Speakers: Not found",
    ]
    assert assistant.next_button.isEnabled()


def test_ac29_play_test_sound_plays_a_generated_tone_and_writes_no_file(
    window, monkeypatch
) -> None:
    played = []
    monkeypatch.setattr(audio_module, "play_pcm", lambda *args, **kw: played.append(args))

    def no_file(*_args, **_kwargs):
        raise AssertionError("the test sound must not write a file")

    monkeypatch.setattr(device_tests_module, "write_tone", no_file)
    monkeypatch.setattr(device_tests_module.tempfile, "mkstemp", no_file)
    assistant = open_setup_assistant(window)
    to_step(assistant, AUDIO)
    assistant.audio.test_sound_button.click()
    assert wait_until(lambda: assistant.audio.result.text() != "")
    samples, rate, index = played[0]
    assert (rate, len(samples), samples.dtype) == (16_000, 16_000, np.int16)  # 1 s
    spectrum = np.abs(np.fft.rfft(samples))
    assert round(np.argmax(spectrum) * rate / len(samples)) == 440
    assert index == window.device_setup.resolved(audio_module.RENDER).endpoint.runtime_index
    assert assistant.audio.result.text() == "Test sound played on 'Test speakers'."


def test_ac05_review_lists_the_required_packs_with_reasons_and_get(window) -> None:
    assistant = open_setup_assistant(window)
    review = reviewed(assistant)
    rows = [label.text() for label in review.row_labels]
    assert rows[0].startswith("Speech recognition German, speech recognition Mandarin")
    assert rows[0].endswith("— Not installed — Needed by: Conversation")
    assert any(row.startswith("Voice Mandarin (Simplified) —") for row in rows)
    voices = [row for row in rows if row.startswith("Voice ")]
    assert voices and all(row.endswith(strings.ASSIST_OPTIONAL_VOICE) for row in voices)
    assert rows[-2:] == [
        "Microphone — Ready — Needed by: Conversation",
        f"Playback device — Ready — {strings.ASSIST_OPTIONAL_VOICE}",
    ]
    assert set(review.get_buttons) == {row.pack_id for row in review.review.rows if row.pack_id}
    assert review.space.text().startswith("Missing packs: ")
    review.get_buttons[STT].click()  # Get… opens the WI-04 details dialog
    assert window.language_packs.details.pack.id == STT
    window.language_packs.details.reject()
    assistant.back_button.click()
    assistant.usage.boxes["meeting"].setChecked(True)
    review = reviewed(assistant)
    voice = next(t.text() for t in review.row_labels if t.text().startswith("Voice Mandarin"))
    assert voice.endswith("Needed by: Meeting dual-mic")  # needed by Meeting, not optional


def test_cap0172_ac31_text_translation_alone(window) -> None:
    assistant = open_setup_assistant(window)
    assistant.usage.boxes["conversation"].setChecked(False)
    assistant.usage.boxes["text-translation"].setChecked(True)
    to_step(assistant, AUDIO)
    assert [label.text() for label in assistant.audio.role_labels] == ["Speakers: Test speakers"]
    review = reviewed(assistant)
    rows = [label.text() for label in review.row_labels]
    assert [row.split(" — ")[0] for row in rows[:2]] == [
        "Translation German → Mandarin (Simplified)",
        "Translation Mandarin (Simplified) → German",
    ]
    assert all(row.endswith("Needed by: Text translation") for row in rows[:2])
    assert all(row.endswith(strings.ASSIST_OPTIONAL_VOICE) for row in rows[2:])
    assert [row[:6] for row in rows[2:]] == ["Voice ", "Voice ", "Playba"]  # no STT, no mic
    assert assistant.finish_button.isVisible() and assistant.finish_button.isEnabled()


def test_ac01_skip_escape_and_finish_store_the_first_run(window, tmp_path, monkeypatch) -> None:
    local = tmp_path / "settings.local.json"
    monkeypatch.setattr(config_module, "LOCAL_CONFIG_PATH", local)
    monkeypatch.setattr(app, "LOCAL_CONFIG_PATH", local)
    window.persist_settings = True
    assistant = open_setup_assistant(window)
    assert open_setup_assistant(window) is assistant  # raised, not duplicated
    QTest.keyClick(assistant, Qt.Key.Key_Escape)
    assert not assistant.isVisible() and window.setup_assistant is None
    stored = json.loads(local.read_text("utf-8"))["provisioning"]
    assert stored["first_run"] == "skipped"
    assert app.load_settings([])[1] is False  # the next launch shows no assistant
    open_page(window).layout.run_assistant_button.click()  # AC-02
    assistant = window.setup_assistant
    assert assistant.isVisible() and assistant.pages.currentIndex() == USAGE
    assistant.usage.boxes["call-bridge"].setChecked(True)
    to_step(assistant, LANGUAGES)
    to_step(assistant, REVIEW)
    assert assistant.finish_button.isVisible() and not assistant.next_button.isVisible()
    assistant.finish_button.click()
    stored = json.loads(local.read_text("utf-8"))["provisioning"]
    assert stored == {
        "first_run": "completed",
        "usages": ["conversation", "call-bridge"],
        "languages": ["de", "zh-Hans"],
    }
    open_setup_assistant(window).skip_button.click()
    assert window.config.provisioning.first_run == "completed"  # Skip never downgrades


def test_ac21_assistant_imports_and_a_session_run_without_any_connection(
    window, shaped, tmp_path, monkeypatch, network
) -> None:
    open_page(window).layout.run_assistant_button.click()
    assistant = window.setup_assistant
    review = reviewed(assistant)
    for pack_id in (STT, MT, MT_BACK):
        pack = window.language_packs.packs.get(pack_id)
        folder = pack_folder(tmp_path / "usb" / pack_id, pack, shaped[2][pack_id])
        monkeypatch.setattr(dialog_module, "pick_folder", lambda _parent, folder=folder: folder)
        review.get_buttons[pack_id].click()
        window.language_packs.details.licence_box.setChecked(True)
        window.language_packs.details.import_folder_action.trigger()
        assert wait_until(
            lambda pack_id=pack_id: (
                review.review is not None
                and pack_id not in review.get_buttons
                and window.language_packs.runner.current is None
            )
        )
    ready = [row for row in review.review.rows if row.pack_id in (STT, MT, MT_BACK)]
    assert [row.status for row in ready] == [ReviewStatus.READY] * 3
    assistant.finish_button.click()
    window.pipeline.catalog.probe.invalidate()
    window.show_workspace(main_window_module.WorkspaceId.CONVERSATION)
    window.conversation.populate_pairs()  # WI-05 refreshes the pairs after a pack job
    window.start_listening()
    assert wait_until(lambda: window.capture.running)
    window.stop_listening()
    assert shaped[1].opened == [] and network == []
