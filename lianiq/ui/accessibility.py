"""Accessible names and keyboard focus targets of the main window (CAP-0169 WI-10).

Several focusable main-window controls carry a visible caption in a plain ``QLabel`` that is
not their buddy, so Windows UI Automation exposed them without a name (WI-08 R5, DEF-04).
They get the caption as accessible name here. The held-turn bar also learns where keyboard
focus goes when it hides with focus inside it (DEF-05). The entry point applies this once
after it builds the window.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lianiq.ui.main_window import MainWindow

# Each control's accessible name is the caption shown above it.
CONTROL_NAMES = {
    "input_combo": "Microphone",
    "output_combo": "Speakers",
    "model_combo": "Model profile",
    "source_text": "Original",
    "target_text": "Translation",
}


def apply_main_window_accessibility(window: MainWindow) -> None:
    """Name the unlabelled controls and set the held-turn bar's focus return targets."""
    for attribute, name in CONTROL_NAMES.items():
        getattr(window, attribute).setAccessibleName(name)
    # While the session runs **Stop** is the next action; after a stop it is **Start**.
    window.held_turn_bar.set_focus_return(window.stop_button, window.start_button)
