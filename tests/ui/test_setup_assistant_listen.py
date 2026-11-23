"""CAP-0170 WI-07 (AC-25): *Listen & translate* in the setup assistant (offscreen).

Split from ``test_setup_assistant`` (file size): the same window, catalog and fake devices.
"""

from __future__ import annotations

from lianiq.ui.setup_assistant import open_setup_assistant
from lianiq.ui.setup_assistant.assistant import AUDIO
from tests._spy_window import spies  # noqa: F401
from tests.packs.conftest import network_attempts  # noqa: F401
from tests.ui._language_packs_helpers import (  # noqa: F401 - the fixtures are imported
    packs_network,
    packs_shaped,
    packs_window,
)
from tests.ui.test_setup_assistant import reviewed, to_step


def test_cap0170_ac25_listen_and_translate_alone(window) -> None:
    assistant = open_setup_assistant(window)
    assistant.usage.boxes["conversation"].setChecked(False)
    assistant.usage.boxes["listen-and-translate"].setChecked(True)
    to_step(assistant, AUDIO)
    assert [label.text() for label in assistant.audio.role_labels] == [
        "Microphone: Test microphone"
    ]
    review = reviewed(assistant)
    rows = [label.text() for label in review.row_labels]
    assert [row.split(" — ")[0] for row in rows] == [
        "Speech recognition German, speech recognition Mandarin (Simplified)",
        "Translation German → Mandarin (Simplified)",
        "Translation Mandarin (Simplified) → German",
        "Microphone",
    ]  # no voice, no Speakers
    assert all(row.endswith("Needed by: Listen & translate") for row in rows[:3])
    assert assistant.finish_button.isVisible() and assistant.finish_button.isEnabled()
