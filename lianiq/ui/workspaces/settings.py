"""The Settings workspace: Voice output and Diagnostics (CAP-0168 spec §2.3.6, WI-02).

- **Voice output** mirrors the *Voice output* checkbox of Conversation: both show the same
  checked, enabled and tooltip state, and toggling either changes the saved preference.
- **Diagnostics** shows the model profile and the compute device as full read-only text
  (AC-12; they left the Conversation layout, RES-06) and a readiness summary of the selected
  pair: conversation, voice output and Call Bridge.

- **Notice history** (WI-03): the redacted diagnostics log with **Copy** and **Export…**
  (``DiagnosticsView``, spec §2.2.6).

Audio devices (WI-04) are added by a later work item. Each value is a keyboard-selectable label, so it is a named Tab stop that is
never shortened: a label without word wrap always gets its full text width.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, Slot
from PySide6.QtWidgets import QCheckBox, QFormLayout, QGroupBox, QLabel, QVBoxLayout, QWidget

from lianiq.call_bridge.controller import check_call_bridge
from lianiq.languages.modes import OutputKind
from lianiq.languages.requirements import ModeAvailability, check
from lianiq.ui import strings
from lianiq.ui.diagnostics_view import DiagnosticsView

if TYPE_CHECKING:
    from lianiq.ui.main_window import MainWindow

_SELECTABLE = (
    Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard
)


def read_only_value(name: str) -> QLabel:
    """A full, selectable, read-only text value named ``name`` for assistive technology."""
    value = QLabel()
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
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        heading = QLabel(strings.NAV_SETTINGS)
        heading.setObjectName("panelTitle")
        layout.addWidget(heading)

        voice = QGroupBox(strings.VOICE_OUTPUT)
        voice_layout = QVBoxLayout(voice)
        self.voice_output_checkbox = QCheckBox(strings.VOICE_OUTPUT)
        self.voice_output_checkbox.setAccessibleName(strings.VOICE_OUTPUT)
        self.voice_output_checkbox.setAccessibleDescription(strings.SETTINGS_VOICE_OUTPUT_HINT)
        self.voice_output_checkbox.toggled.connect(self._voice_output_toggled)
        voice_layout.addWidget(self.voice_output_checkbox)
        hint = QLabel(strings.SETTINGS_VOICE_OUTPUT_HINT)
        hint.setWordWrap(True)
        voice_layout.addWidget(hint)
        layout.addWidget(voice)

        diagnostics = QGroupBox(strings.DIAG_TITLE)
        form = QFormLayout(diagnostics)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.model_profile_field = read_only_value(strings.DIAG_MODEL_PROFILE)
        self.compute_device_field = read_only_value(strings.DIAG_COMPUTE_DEVICE)
        self.readiness_field = read_only_value(strings.DIAG_READINESS)
        for caption, field in (
            (strings.DIAG_MODEL_PROFILE, self.model_profile_field),
            (strings.DIAG_COMPUTE_DEVICE, self.compute_device_field),
            (strings.DIAG_READINESS, self.readiness_field),
        ):
            label = QLabel(caption)
            label.setBuddy(field)
            form.addRow(label, field)
        layout.addWidget(diagnostics)
        self.diagnostics_view = DiagnosticsView(self.host)
        layout.addWidget(self.diagnostics_view, 1)
        self.model_profile_field.setText(strings.DIAG_MODEL_PROFILE_BALANCED)

        conversation = self.host.conversation
        conversation.voice_output_changed.connect(self.sync_voice_output)
        conversation.tts_checkbox.toggled.connect(self.sync_voice_output)
        self.refresh()
        return page

    # Voice output mirror --------------------------------------------------------------------

    @Slot()
    def sync_voice_output(self) -> None:
        """Show the Conversation checkbox state; the saved preference stays with it."""
        source = self.host.conversation.tts_checkbox
        mirror = self.voice_output_checkbox
        mirror.blockSignals(True)
        mirror.setChecked(source.isChecked())
        mirror.blockSignals(False)
        mirror.setEnabled(source.isEnabled())
        mirror.setToolTip(source.toolTip())

    @Slot(bool)
    def _voice_output_toggled(self, checked: bool) -> None:
        source = self.host.conversation.tts_checkbox
        if source.isEnabled():
            source.setChecked(checked)  # runs the Conversation toggle: preference + gate
        self.sync_voice_output()

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
        self.sync_voice_output()
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
        spoken = check(
            conversation.conversation_session(pair, fixed_source, OutputKind.SPOKEN),
            controller.catalog,
            devices,
        )
        voice_missing = tuple(item for item in spoken.missing if item not in text.missing)
        call_bridge = self.host.call_bridge
        try:
            bridge = check_call_bridge(
                call_bridge.session(),
                self.host.pipeline.catalog,
                call_bridge.panel.assigned_roles(),
            )
        except Exception:  # noqa: BLE001 - an invalid Call Bridge setting reads as not ready.
            bridge = ModeAvailability(False, ())
        return [
            row(item=strings.PAIR_LABEL, status=conversation.pairs.pair_name(pair)),
            row(item=strings.NAV_CONVERSATION, status=self._status(text)),
            row(
                item=strings.VOICE_OUTPUT,
                status=self._status(ModeAvailability(not voice_missing, voice_missing)),
            ),
            row(item=strings.NAV_CALL_BRIDGE, status=self._status(bridge)),
        ]

    def _status(self, availability: ModeAvailability) -> str:
        if availability.available:
            return strings.DIAG_READY
        if not availability.missing:
            return strings.MODE_UNAVAILABLE.format(items="—")
        return self.host.describe_missing(availability)
