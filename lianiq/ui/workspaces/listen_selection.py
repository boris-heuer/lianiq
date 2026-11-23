"""Language and microphone selection of the Listen page (CAP-0170 spec §2.2.1 steps 2-3).

``ListenWorkspace`` base (file-size split). The combos list every registry language by
English name; choosing the language shown in the other combo swaps them. *Microphone* lists
the Conversation capture inventory (``DeviceSetup.state``) with ``Follow Windows default
(now: <name>)`` first; a missing saved device stays selected as unavailable and is never
replaced. Choices are written to ``config.listen``; display names are never stored.
"""

from __future__ import annotations

from lianiq.audio.device_selection import (
    FOLLOW_DEFAULT,
    DeviceChoice,
    DevicePolicy,
    ResolvedDevice,
    UnusableEndpoint,
    display_labels,
    resolve_choice,
    unusable_reason,
)
from lianiq.call_bridge.contracts import EndpointFlow
from lianiq.languages.errors import LanguageContractError
from lianiq.languages.modes import SessionPair
from lianiq.languages.registry import Availability
from lianiq.languages.requirements import DeviceReadiness, check
from lianiq.listen.session import listen_session
from lianiq.ui import strings

MISSING = "\0missing"  # combo data of the "Saved device — unavailable" item
CAPTURE = EndpointFlow.CAPTURE


class ListenSelection:
    """The current direction and microphone, and the combos that choose them."""

    def _usable(self) -> list[str]:
        languages = self.registry.languages()
        return [item.id for item in languages if item.availability is not Availability.PLANNED]

    def _defaults(self) -> tuple[str, str]:
        """``listen.*`` when registered, else ``languages.pair``; nothing is rewritten."""
        usable, pair = self._usable(), self.host.config.languages.pair
        source = self.config.source_language
        target = self.config.target_language
        source = source if source in usable else pair[0]
        target = target if target in usable and target != source else pair[1]
        return (source, pair[0] if target == source else target)

    def session(self) -> SessionPair | None:
        try:
            return listen_session(self.registry.pair(self.source, self.target), self.source)
        except LanguageContractError:
            return None  # shown as an unsupported direction

    def choice(self) -> DeviceChoice:
        if self.config.input_policy == DevicePolicy.EXPLICIT.value:
            return DeviceChoice(DevicePolicy.EXPLICIT, self.config.input_endpoint_id)
        return FOLLOW_DEFAULT

    def microphone(self) -> ResolvedDevice:
        inventory = self.host.device_setup.state.inventory
        return resolve_choice(
            self.choice(), inventory.endpoints, CAPTURE, inventory.default(CAPTURE)
        )

    def _language_chosen(self, combo) -> None:
        language = combo.currentData()
        if language is None:
            return
        if combo is self.source_combo:
            self.source, self.target = (
                language,
                (self.source if language == self.target else self.target),
            )
        else:
            self.source, self.target = (
                (self.target if language == self.source else self.source),
                language,
            )
        self._changed()

    def _swap(self) -> None:
        self.source, self.target = self.target, self.source
        self._changed()

    def _changed(self) -> None:
        self.config.source_language, self.config.target_language = self.source, self.target
        self._sync_combos()
        self.refresh()

    def _sync_combos(self) -> None:
        for combo, language in ((self.source_combo, self.source), (self.target_combo, self.target)):
            index = combo.findData(language)
            if index >= 0:
                combo.setCurrentIndex(index)

    def load_microphones(self) -> None:
        """The Conversation capture inventory; a missing saved device stays selected."""
        inventory = self.host.device_setup.state.inventory
        combo = self.microphone_combo
        combo.blockSignals(True)
        combo.clear()
        follow = resolve_choice(
            FOLLOW_DEFAULT, inventory.endpoints, CAPTURE, inventory.default(CAPTURE)
        )
        combo.addItem(follow.label, None)
        labels = display_labels(inventory.endpoints)
        for endpoint in inventory.endpoints:
            if endpoint.flow is not CAPTURE:
                continue
            unusable = isinstance(endpoint, UnusableEndpoint)
            text = labels[endpoint.endpoint_id]
            if unusable:
                text = strings.DEVICE_UNUSABLE.format(name=text, reason=unusable_reason(CAPTURE))
            combo.addItem(text, endpoint.endpoint_id)
            combo.model().item(combo.count() - 1).setEnabled(not unusable)
        index = 0
        if self.choice().policy is DevicePolicy.EXPLICIT:
            index = combo.findData(self.config.input_endpoint_id)
            if index < 0:
                combo.addItem(strings.DEVICE_UNAVAILABLE.format(name=strings.DEVICE_SAVED), MISSING)
                index = combo.count() - 1
                combo.model().item(index).setEnabled(False)
        combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def _microphone_chosen(self, _index: int) -> None:
        endpoint = self.microphone_combo.currentData()
        if endpoint == MISSING:
            return
        policy = DevicePolicy.FOLLOW_DEFAULT if endpoint is None else DevicePolicy.EXPLICIT
        self.config.input_policy, self.config.input_endpoint_id = policy.value, endpoint
        self.refresh()

    def _no_packs(self) -> bool:
        """No source recogniser with a translation edge for any registry direction."""
        usable, catalog_ = self._usable(), self.host.pipeline.catalog
        devices = DeviceReadiness(microphone=True)
        for source in usable:
            for target in usable:
                if source == target:
                    continue
                try:
                    session = listen_session(self.registry.pair(source, target), source)
                except LanguageContractError:
                    continue
                if not check(session, catalog_, devices).missing:
                    return False
        return True
