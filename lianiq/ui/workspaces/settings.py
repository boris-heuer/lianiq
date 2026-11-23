"""The Settings workspace: Audio devices, Voice output, Diagnostics (CAP-0168 spec §2.3.6).

- **Voice output** mirrors the voice rows of Conversation (CAP-0167 contract.md §7): the same
  switches, states, actions and locks; a switch toggled or a **Voice options…** change in
  either place changes the saved choice and refreshes both. A hint names the voices Call
  Bridge and Meeting need.
- **Diagnostics** shows the model profile and the compute device as full read-only text
  (AC-12; they left the Conversation layout, RES-06) and a readiness summary of the selected
  pair: conversation, one voice row per pair language and Call Bridge, with the **Open Language
  packs** link.

- **Notice history** (WI-03): the redacted diagnostics log with **Copy** and **Export…**
  (``DiagnosticsView``, spec §2.2.6).

- **Audio devices** (WI-04): Microphone and Speakers by endpoint identity, **Refresh** and
  the device tests (``DeviceSetup``, spec §2.3.5).

Each value is a keyboard-selectable label, so it is a named Tab stop that is never
shortened: a label without word wrap always gets its full text width.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, Slot
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from lianiq.call_bridge.controller import check_call_bridge
from lianiq.conversation.spoken_output import VoiceState
from lianiq.languages.modes import OutputKind
from lianiq.languages.requirements import ModeAvailability, check
from lianiq.ui import strings
from lianiq.ui.diagnostics_view import DiagnosticsView
from lianiq.ui.shell.scroll import workspace_scroll
from lianiq.ui.voice_output_rows import VoiceOutputRows, state_text

if TYPE_CHECKING:
    from lianiq.ui.main_window import MainWindow

_SELECTABLE = (
    Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard
)


def read_only_value(name: str) -> QLabel:
    """A full, selectable, read-only text value named ``name`` for assistive technology."""
    value = QLabel()
    value.setObjectName("readOnlyValue")  # the stylesheet's focus outline (WI-05)
    value.setTextFormat(Qt.TextFormat.PlainText)
    value.setTextInteractionFlags(_SELECTABLE)
    value.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    value.setAccessibleName(name)
    return value


class SettingsWorkspace(QObject):
    def __init__(self, host: MainWindow) -> None:
        super().__init__(host)
        self.host = host

    def build_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("settingsPage")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        # WI-05: the sections scroll when the window is smaller than their minimum.
        content = QWidget()
        page_layout.addWidget(workspace_scroll(content), 1)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        heading = QLabel(strings.NAV_SETTINGS)
        heading.setObjectName("panelTitle")
        layout.addWidget(heading)

        layout.addWidget(self.host.device_setup.build_group())  # Audio devices (WI-04)

        conversation = self.host.conversation
        voice = QGroupBox(strings.VOICE_SECTION)
        voice_layout = QVBoxLayout(voice)
        self.voice_rows = VoiceOutputRows(voice)
        self.voice_rows.switched.connect(conversation._voice_switched)
        self.voice_rows.packs_requested.connect(conversation.open_language_packs)
        self.voice_rows.options_requested.connect(conversation.open_voice_options)
        self.voice_rows.replay_requested.connect(conversation.replay_spoken)
        self.voice_rows.stop_playback_requested.connect(conversation.stop_spoken)
        voice_layout.addWidget(self.voice_rows)
        hint = QLabel(strings.VOICE_REQUIREMENTS_HINT)
        hint.setWordWrap(True)
        voice_layout.addWidget(hint)
        layout.addWidget(voice)

        diagnostics = QGroupBox(strings.DIAG_TITLE)
        form = QFormLayout(diagnostics)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.model_profile_field = read_only_value(strings.DIAG_MODEL_PROFILE)
        self.compute_device_field = read_only_value(strings.DIAG_COMPUTE_DEVICE)
        self.readiness_field = read_only_value(strings.DIAG_READINESS)
        # WI-05: a long row (e.g. Call Bridge) wraps instead of being cut or scrolled sideways.
        self.readiness_field.setWordWrap(True)
        for caption, field in (
            (strings.DIAG_MODEL_PROFILE, self.model_profile_field),
            (strings.DIAG_COMPUTE_DEVICE, self.compute_device_field),
            (strings.DIAG_READINESS, self.readiness_field),
        ):
            label = QLabel(caption)
            label.setBuddy(field)
            form.addRow(label, field)
        # CAP-0171 C §12: the readiness rows link to the Language packs page (AC-34).
        self.packs_link = QPushButton(strings.PACKS_OPEN)
        self.packs_link.setAccessibleName(strings.PACKS_OPEN)
        self.packs_link.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.packs_link.clicked.connect(self.host.conversation.open_packs)
        form.addRow("", self.packs_link)
        layout.addWidget(diagnostics)
        self.diagnostics_view = DiagnosticsView(self.host)
        layout.addWidget(self.diagnostics_view, 1)
        self.model_profile_field.setText(strings.DIAG_MODEL_PROFILE_BALANCED)

        conversation.voice_rows_changed.connect(self.sync_voice_rows)
        self.refresh()
        return page

    # Voice output mirror --------------------------------------------------------------------

    @Slot()
    def sync_voice_rows(self) -> None:
        """Show the rows, switch lock and playback of Conversation; both write ``tts.output``."""
        conversation = self.host.conversation
        self.voice_rows.set_rows(
            conversation.voice_statuses_shown,
            conversation.voice_preferences,
            conversation.voice_controls_shown,
        )
        self.voice_rows.set_switches_locked(conversation.voice_lock)
        self.voice_rows.set_options_locked(*conversation.voice_options_lock)
        self.voice_rows.set_playback(conversation.playback_state, conversation.can_replay())

    # Diagnostics ----------------------------------------------------------------------------

    def refresh(self) -> None:
        """Re-read the compute device and the readiness summary (the page is shown)."""
        conversation = self.host.conversation
        self.compute_device_field.setText(
            strings.DIAG_COMPUTE_VALUE.format(
                recognition=conversation.recognition_device().upper(),
                translation=conversation.translation_device().upper(),
            )
        )
        self.readiness_field.setText("\n".join(self.readiness_rows()))
        self.sync_voice_rows()
        self.diagnostics_view.refresh()

    def readiness_rows(self) -> list[str]:
        """One line per item: the selected pair, conversation, voice output and Call Bridge."""
        conversation = self.host.conversation
        row = strings.DIAG_READINESS_ROW.format
        pair = conversation.current_pair()
        if pair is None:
            return [row(item=strings.PAIR_LABEL, status=strings.NO_PAIR_READY)]
        controller = conversation.session_controller
        devices = conversation.device_readiness()
        fixed_source = conversation.current_fixed_source()
        text = check(
            conversation.conversation_session(pair, fixed_source, OutputKind.TEXT),
            controller.catalog,
            devices,
        )
        call_bridge = self.host.call_bridge
        try:
            bridge = check_call_bridge(
                call_bridge.session(),
                self.host.pipeline.catalog,
                call_bridge.panel.assigned_roles(),
            )
        except Exception:  # noqa: BLE001 - an invalid Call Bridge setting reads as not ready.
            bridge = ModeAvailability(False, ())
        statuses = conversation.voice_statuses()
        registry = self.host.pipeline.registry
        voices = [
            row(
                item=strings.VOICE_READINESS_ROW.format(
                    language=registry.display_name(status.language)
                ),
                status=strings.DIAG_READY
                if status.state is VoiceState.READY
                else state_text(status, registry, statuses),
            )
            for status in statuses
        ]
        return [
            row(item=strings.PAIR_LABEL, status=conversation.pairs.pair_name(pair)),
            row(item=strings.NAV_CONVERSATION, status=self._status(text)),
            *voices,
            row(item=strings.NAV_CALL_BRIDGE, status=self._status(bridge)),
        ]

    def _status(self, availability: ModeAvailability) -> str:
        if availability.available:
            return strings.DIAG_READY
        if not availability.missing:
            return strings.MODE_UNAVAILABLE.format(items="—")
        return self.host.describe_missing(availability)
