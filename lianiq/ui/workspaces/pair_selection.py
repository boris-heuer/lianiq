"""The language pair and direction controls of the Conversation workspace (CAP-0168 WI-01).

Moved behaviour-neutrally out of ``ui/main_window.py``: the pair combo lists the ready
qualified pairs and the planned languages; the direction combo lists Automatic and both fixed
directions of the selected pair, labelled with registry names.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable

from PySide6.QtWidgets import QComboBox, QGridLayout, QLabel

from lianiq.config import AppConfig
from lianiq.languages.capabilities import CapabilityCatalog
from lianiq.languages.errors import LanguageContractError
from lianiq.languages.modes import InputKind, OutputKind, RoutingKind, SessionPair, UsageMode
from lianiq.languages.registry import Availability, LanguageId, LanguagePair, LanguageRegistry
from lianiq.languages.requirements import DeviceReadiness, check
from lianiq.ui import strings

# ``mode_combo`` item data: a fixed source language ID, or this value for Automatic.
AUTOMATIC_ROUTING = ""
ROUTING_CONTROL_LABEL = "Conversation direction"
# A pair is ready when one of its main-window routings has every model it needs.
MODELS_ONLY = DeviceReadiness(microphone=True, playback=True)


def conversation_session(
    pair: LanguagePair, fixed_source: LanguageId | None, output: OutputKind
) -> SessionPair:
    routing = RoutingKind.BIDIRECTIONAL if fixed_source is None else RoutingKind.FIXED
    return SessionPair(
        pair, UsageMode(InputKind.MICROPHONE, routing, output), fixed_source=fixed_source
    )


def add_disabled_item(combo: QComboBox, text: str) -> None:
    """A visible entry that cannot be selected; its state is part of its text."""
    combo.addItem(text, None)
    item = combo.model().item(combo.count() - 1)
    item.setEnabled(False)
    item.setSelectable(False)
    item.setToolTip(text)


class PairSelection:
    def __init__(
        self,
        config: AppConfig,
        registry: LanguageRegistry,
        catalog: Callable[[], CapabilityCatalog],
    ) -> None:
        self.config = config
        self.registry = registry
        self._catalog = catalog
        self._ready_pairs: list[LanguagePair] = []

    def build(self, controls: QGridLayout) -> None:
        """The labelled pair (column 0) and direction (column 1) combos."""
        pair_label = QLabel(strings.PAIR_LABEL)
        controls.addWidget(pair_label, 0, 0)
        self.pair_combo = QComboBox()
        self.pair_combo.setAccessibleName(strings.PAIR_LABEL)
        pair_label.setBuddy(self.pair_combo)
        controls.addWidget(self.pair_combo, 1, 0)
        routing_label = QLabel(ROUTING_CONTROL_LABEL)
        controls.addWidget(routing_label, 0, 1)
        self.mode_combo = QComboBox()
        self.mode_combo.setAccessibleName(ROUTING_CONTROL_LABEL)
        routing_label.setBuddy(self.mode_combo)
        controls.addWidget(self.mode_combo, 1, 1)

    def current_fixed_source(self) -> LanguageId | None:
        """The fixed source the routing control selects, or ``None`` for Automatic."""
        data = self.mode_combo.currentData()
        return LanguageId(data) if data else None

    def current_pair(self) -> LanguagePair | None:
        """The selected language pair; ``None`` if no ready pair can be selected."""
        data = self.pair_combo.currentData()
        return data if isinstance(data, LanguagePair) else None

    def pair_name(self, pair: LanguagePair) -> str:
        name = self.registry.display_name
        return strings.PAIR_NAME.format(a=name(pair.first), b=name(pair.second))

    def _pair_ready(self, pair: LanguagePair) -> bool:
        catalog = self._catalog()
        return any(
            check(
                conversation_session(pair, source, OutputKind.TEXT), catalog, MODELS_ONLY
            ).available
            for source in (None, *pair.members)
        )

    def populate_pairs(self) -> tuple[str, str]:
        """Ready qualified pairs, then every planned language as a disabled entry (AC-02).

        Returns the window title and the *Original* placeholder for the selected pair.
        """
        registry = self.registry
        qualified = [
            item.id for item in registry.languages() if item.availability is Availability.QUALIFIED
        ]
        pairs = [registry.pair(a, b) for a, b in itertools.combinations(qualified, 2)]
        self._ready_pairs = [pair for pair in pairs if self._pair_ready(pair)]
        self.pair_combo.blockSignals(True)
        self.pair_combo.clear()
        for pair in self._ready_pairs:
            self.pair_combo.addItem(self.pair_name(pair), pair)
        if not self._ready_pairs:
            add_disabled_item(self.pair_combo, strings.PAIR_NONE_READY)
        for item in registry.languages():
            if item.availability is Availability.PLANNED:
                add_disabled_item(
                    self.pair_combo, f"{item.english_name} {strings.PAIR_PLANNED_SUFFIX}"
                )
        try:
            configured = registry.pair(*self.config.languages.pair)
        except LanguageContractError:
            configured = None  # an unusable saved pair falls back to the first ready one
        index = self._ready_pairs.index(configured) if configured in self._ready_pairs else 0
        self.pair_combo.setCurrentIndex(index)
        self.pair_combo.blockSignals(False)
        languages = self.config.languages
        selected = self.current_pair()
        if selected is not None and selected != configured:
            languages.pair = list(selected.members)
            languages.routing, languages.fixed_source = "bidirectional", None
        fixed = LanguageId(languages.fixed_source) if languages.routing == "fixed" else None
        return self.populate_routing(selected, fixed)

    def populate_routing(
        self, pair: LanguagePair | None, fixed_source: LanguageId | None
    ) -> tuple[str, str]:
        """Automatic and both fixed directions of ``pair``, labelled with registry names.

        Returns the window title and the *Original* placeholder for ``pair``.
        """
        name = self.registry.display_name
        self.mode_combo.blockSignals(True)
        self.mode_combo.clear()
        title, placeholder = "lianiq", "Speak …"
        if pair is not None:
            self.mode_combo.addItem(
                strings.ROUTING_AUTOMATIC.format(a=name(pair.first), b=name(pair.second)),
                AUTOMATIC_ROUTING,
            )
            for source in pair.members:
                label = strings.ROUTING_FIXED.format(
                    source=name(source), target=name(pair.other(source))
                )
                self.mode_combo.addItem(label, source)
            source = fixed_source if fixed_source in pair else None
            found = self.mode_combo.findData(source or AUTOMATIC_ROUTING)
            self.mode_combo.setCurrentIndex(max(found, 0))
            title = strings.WINDOW_TITLE.format(pair=self.pair_name(pair))
            placeholder = f"Speak in {name(pair.first)} or {name(pair.second)} …"
        self.mode_combo.blockSignals(False)
        return title, placeholder
