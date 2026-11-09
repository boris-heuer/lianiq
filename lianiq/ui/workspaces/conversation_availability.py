"""Pair, routing and availability of ``ConversationWorkspace`` (CAP-0168 file-size split)."""

from __future__ import annotations

from PySide6.QtCore import Slot

from lianiq.hardware import ctranslate2_cuda_available, resolve_compute_device
from lianiq.languages.errors import PairLockedError
from lianiq.languages.modes import OutputKind, SessionPair
from lianiq.languages.registry import LanguageId, LanguagePair
from lianiq.languages.requirements import DeviceReadiness, ModeAvailability, check
from lianiq.ui import strings
from lianiq.ui.workspaces.pair_selection import conversation_session


class ConversationAvailability:
    """``ConversationWorkspace`` base: the selected pair and routing and what is ready."""

    def connect_selection(self) -> None:
        self.populate_pairs()
        self.pair_combo.currentIndexChanged.connect(self._pair_selected)
        self.mode_combo.currentIndexChanged.connect(self._routing_selected)
        self.refresh_availability()

    def current_fixed_source(self) -> LanguageId | None:
        """The fixed source the routing control selects, or ``None`` for Automatic."""
        return self.pairs.current_fixed_source()

    def current_pair(self) -> LanguagePair | None:
        """The selected language pair; ``None`` if no ready pair can be selected."""
        return self.pairs.current_pair()

    def device_readiness(self) -> DeviceReadiness:
        """Microphone and playback availability from the enumerated audio devices."""
        return DeviceReadiness(
            microphone=any(device.inputs for device in self.devices),
            playback=any(device.outputs for device in self.devices),
        )

    conversation_session = staticmethod(conversation_session)

    def populate_pairs(self) -> None:
        """Ready qualified pairs, then every planned language as a disabled entry (AC-02)."""
        self._show_pair(*self.pairs.populate_pairs())

    def _populate_routing(self, pair: LanguagePair | None, fixed_source: LanguageId | None) -> None:
        self._show_pair(*self.pairs.populate_routing(pair, fixed_source))

    def _show_pair(self, title: str, placeholder: str) -> None:
        self.host.setWindowTitle(title)
        self.source_text.setPlaceholderText(placeholder)

    def refresh_availability(self) -> None:
        """Drive the routing entries, *Voice output* and **Start** from ``check()``."""
        if self.host.session_locked():
            return
        try:
            self._refresh_availability()
        finally:
            self.voice_output_changed.emit()

    def _refresh_availability(self) -> None:
        status = self.host.statusBar()
        pair = self.current_pair()
        for control in (self.mode_combo, self.swap_button):
            control.setEnabled(pair is not None)
        if pair is None:
            self.start_button.setEnabled(False)
            self.tts_checkbox.setEnabled(False)
            self.state_label.setText("Not available")
            status.showMessage(strings.NO_PAIR_READY)
            return
        catalog = self.session_controller.catalog
        devices = self.device_readiness()
        model = self.mode_combo.model()
        for index in range(self.mode_combo.count()):
            data = self.mode_combo.itemData(index)
            entry = self.conversation_session(
                pair, LanguageId(data) if data else None, OutputKind.TEXT
            )
            availability = check(entry, catalog, devices)
            item = model.item(index)
            item.setEnabled(availability.available)
            item.setToolTip(
                "" if availability.available else self.host.describe_missing(availability)
            )
        fixed_source = self.current_fixed_source()
        text = check(
            self.conversation_session(pair, fixed_source, OutputKind.TEXT), catalog, devices
        )
        spoken = check(
            self.conversation_session(pair, fixed_source, OutputKind.SPOKEN), catalog, devices
        )
        # Voice readiness never makes text output unavailable (IS §7).
        voice_missing = tuple(item for item in spoken.missing if item not in text.missing)
        voice_text = (
            self.host.describe_missing(ModeAvailability(False, voice_missing))
            if voice_missing
            else ""
        )
        self.tts_checkbox.setEnabled(not voice_missing)
        self.tts_checkbox.setToolTip(voice_text)
        self.notices.voice(voice_text)
        self.tts_checkbox.blockSignals(True)
        self.tts_checkbox.setChecked(self.config.voice_output and not voice_missing)
        self.tts_checkbox.blockSignals(False)
        availability = self.session_controller.availability(self.session_pair())
        self.start_button.setEnabled(availability.available)
        self.notices.availability(availability.available)
        if availability.available:
            if self.state_label.text() == "Not available":
                self.state_label.setText("Ready")
            status.showMessage("Models load on Start, only for the selected mode.")
        else:
            self.state_label.setText("Not available")
            status.showMessage(self.host.describe_missing(availability))

    @Slot(int)
    def _pair_selected(self, _index: int) -> None:
        pair = self.current_pair()
        if pair is None or self.host.session_locked():
            return
        languages = self.config.languages
        fixed_source = self.current_fixed_source()
        if fixed_source not in pair:
            fixed_source = None
        languages.pair = list(pair.members)
        languages.routing = "bidirectional" if fixed_source is None else "fixed"
        languages.fixed_source = fixed_source
        # The Call Bridge lanes and labels follow the pair and ``call_bridge.local_language``.
        self.host.call_bridge.update_languages()
        self._populate_routing(pair, fixed_source)
        self._selection_changed()

    @Slot(int)
    def _routing_selected(self, _index: int) -> None:
        if not self.host.session_locked():
            self._selection_changed()

    def _selection_changed(self) -> None:
        """A stopped selection change selects the next session (``SessionController.change``)."""
        try:
            self.session_controller.change(self.session_pair())
        except PairLockedError:
            self.notices.pair_locked()
            return
        self.refresh_availability()

    def recognition_device(self) -> str:
        """The compute device speech recognition runs (or will run) on."""
        return self._recognition_device()

    def translation_device(self) -> str:
        """The compute device translation runs (or will run) on."""
        device = getattr(self.pipeline.translator, "device", None)
        if device is None:
            device = resolve_compute_device(
                self.config.translation.device, ctranslate2_cuda_available()
            )
        return device

    def _recognition_device(self) -> str:
        device = getattr(self.pipeline.recognizer, "device", None)
        if device is None:
            # The recogniser is built on Start; report the device it will use.
            device = resolve_compute_device(
                self.config.speech_to_text.device, ctranslate2_cuda_available()
            )
        return device

    def session_pair(self) -> SessionPair:
        """The conversation session the current controls select (microphone input)."""
        pair = self.current_pair()
        if pair is None:
            raise RuntimeError(strings.NO_PAIR_READY)
        output = OutputKind.SPOKEN if self.tts_checkbox.isChecked() else OutputKind.TEXT
        return self.conversation_session(pair, self.current_fixed_source(), output)

    @Slot(bool)
    def _toggle_tts(self, enabled: bool) -> None:
        # The saved preference; a running session keeps the output it was started with.
        self.config.voice_output = enabled
        self.refresh_availability()

    @Slot()
    def _swap_direction(self) -> None:
        """Fixed source to the other member; Automatic to the first available direction."""
        pair = self.current_pair()
        if pair is None or self.host.session_locked():
            return
        current = self.current_fixed_source()
        candidates = pair.members if current is None else (pair.other(current),)
        model = self.mode_combo.model()
        for source in candidates:
            index = self.mode_combo.findData(source)
            if model.item(index).isEnabled():
                self.mode_combo.setCurrentIndex(index)
                self.notices.direction(None)
                return
        # Spec §2.3.4 "mode unavailable": an info notice; the direction stays unchanged.
        self.notices.direction(model.item(self.mode_combo.findData(candidates[0])).toolTip())
