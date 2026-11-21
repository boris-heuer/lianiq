"""The Text translation workspace (CAP-0172 WI-02): type or paste, then Translate.

Sidebar entry *Text translation*, third (Ctrl+3). Nothing is translated while typing:
**Translate**, Ctrl+Return or Ctrl+keypad-Enter starts one request through
``TextTranslationController``. The page never writes the source editor after the user
types, so caret and selection survive every status update, and it reads the clipboard
never: Copy only writes it. Worker callbacks reach the GUI thread through a queued signal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut

from lianiq.call_bridge.contracts import EndpointFlow
from lianiq.languages.errors import LanguageContractError
from lianiq.languages.registry import Availability
from lianiq.languages.requirements import describe
from lianiq.text_translation.controller import TextSnapshot, TextTranslationController
from lianiq.text_translation.jobs import TranslationJobs
from lianiq.text_translation.limits import MAX_SOURCE_CODE_POINTS, SourceCheck
from lianiq.text_translation.readiness import TranslateBlock
from lianiq.text_translation.state import ResultState
from lianiq.ui import strings
from lianiq.ui.workspaces.text_translation_layout import TextTranslationLayout

if TYPE_CHECKING:
    from lianiq.ui.main_window import MainWindow

_SUBMIT_KEYS = (Qt.Key.Key_Return, Qt.Key.Key_Enter)
COPIED_MS = 1500


class TextTranslationWorkspace(TextTranslationLayout, QObject):
    posted = Signal(object)  # a worker callback, run on the GUI thread

    def __init__(self, host: MainWindow) -> None:
        super().__init__(host)
        self.host = host
        self.registry = host.pipeline.registry
        self.posted.connect(self._run_posted)  # queued: the receiver lives on the GUI thread
        self.jobs = TranslationJobs(host.pipeline.text_translator, self.posted.emit)
        self.controller = TextTranslationController(
            self.registry,
            lambda: host.pipeline.catalog,
            lambda: None,  # pack catalog: wired with the Language packs page (CAP-0171)
            self.jobs,
            lambda: host.device_setup.resolved(EndpointFlow.RENDER),
            self.render,
            self._default_languages(),
            notify=host.post_notice,
            resolve=host.resolve_notices,
        )
        self._shown_result: int | None = None

    def _default_languages(self):
        try:
            pair = self.registry.pair(*self.host.config.languages.pair)
        except LanguageContractError:
            pair = None
        if pair is not None:
            return pair.members
        languages = self.registry.languages()
        usable = [item.id for item in languages if item.availability is not Availability.PLANNED]
        return usable[0], usable[1]

    def build_page(self):
        page = super().build_page()
        self._select(self.source_combo, self.controller.draft.source)
        self._select(self.target_combo, self.controller.draft.target)
        self.source_combo.activated.connect(lambda _index: self._combo_changed(self.source_combo))
        self.target_combo.activated.connect(lambda _index: self._combo_changed(self.target_combo))
        self.swap_button.clicked.connect(self._swap)
        self.source_edit.textChanged.connect(
            lambda: self.controller.source_changed(self.source_edit.toPlainText())
        )
        self.source_edit.installEventFilter(self)
        page.installEventFilter(self)
        for key in ("Ctrl+Return", "Ctrl+Enter"):
            shortcut = QShortcut(QKeySequence(key), page, activated=self.controller.translate)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        escape = QShortcut(QKeySequence("Escape"), page, activated=self.controller.cancel)
        escape.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.translate_button.clicked.connect(self._translate_clicked)
        self.retry_button.clicked.connect(self.controller.retry)
        self.copy_source_button.clicked.connect(
            lambda: self._copy(self.copy_source_button, self.source_edit.toPlainText())
        )
        self.copy_translation_button.clicked.connect(self._copy_translation)
        self.render(self.controller.snapshot())
        return page

    # Events.

    @Slot(object)
    def _run_posted(self, callback) -> None:
        callback()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.source_edit and event.type() == QEvent.Type.KeyPress:
            control = event.modifiers() & Qt.KeyboardModifier.ControlModifier
            if control and event.key() in _SUBMIT_KEYS:
                self.controller.translate()
                return True
        elif watched is getattr(self, "page", None) and event.type() == QEvent.Type.Show:
            self.controller.refresh()  # devices or packs may have changed elsewhere
            QTimer.singleShot(0, self.source_edit.setFocus)
        return False

    def _translate_clicked(self) -> None:
        if self.controller.cancellable:
            self.controller.cancel()
        else:
            self.controller.translate()

    def _combo_changed(self, combo) -> None:
        language = combo.currentData()
        if language is None:
            return
        source, target = self.controller.draft.source, self.controller.draft.target
        if combo is self.source_combo:
            pair = (language, source if language == target else target)
        else:
            pair = (target if language == source else source, language)
        self.controller.languages_changed(*pair)
        self._sync_combos()

    def _swap(self) -> None:
        self.controller.swap()
        self._sync_combos()

    def _sync_combos(self) -> None:
        self._select(self.source_combo, self.controller.draft.source)
        self._select(self.target_combo, self.controller.draft.target)

    @staticmethod
    def _select(combo, language) -> None:
        index = combo.findData(language)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _copy(self, button, text: str) -> None:
        QGuiApplication.clipboard().setText(text)
        label = button.accessibleName()
        button.setText(strings.TEXT_COPIED)
        QTimer.singleShot(COPIED_MS, lambda: button.setText(label))

    def _copy_translation(self) -> None:
        text = self.controller.current_translation()
        if text is not None:
            self._copy(self.copy_translation_button, text)

    def shutdown(self) -> None:
        self.controller.shutdown()

    # Rendering.

    def render(self, snapshot: TextSnapshot) -> None:
        if not hasattr(self, "page"):
            return
        self.counter_label.setText(
            strings.TEXT_COUNTER.format(count=snapshot.length, limit=MAX_SOURCE_CODE_POINTS)
        )
        self.counter_label.setProperty("warning", snapshot.check is SourceCheck.TOO_LONG)
        self.readiness_label.setText(self._readiness_text(snapshot))
        self.readiness_label.setVisible(bool(self.readiness_label.text()))
        self.busy_indicator.setVisible(snapshot.translating)
        if self.controller.cancellable:
            self.translate_button.setText(strings.TEXT_CANCEL)
            self.translate_button.setEnabled(True)
        else:
            self.translate_button.setText(strings.TEXT_TRANSLATE)
            self.translate_button.setEnabled(self.controller.can_translate())
        self.retry_button.setVisible(snapshot.retry)
        self.status_label.setText(
            strings.TEXT_TRANSLATING if snapshot.translating else snapshot.status or ""
        )
        result = self.controller.draft.result
        result_id = None if result is None else result.result_id
        if result_id != self._shown_result:
            self.result_edit.setPlainText(snapshot.result_text or "")
            self._shown_result = result_id
        stale = snapshot.result_state is ResultState.STALE
        self.stale_label.setVisible(stale)
        self.result_edit.setEnabled(not stale)  # dims the out-of-date text
        self.result_edit.setAccessibleDescription(
            " ".join(
                text
                for text in (strings.TEXT_STALE if stale else "", self.status_label.text())
                if text
            )
        )
        self.copy_translation_button.setEnabled(snapshot.result_state is ResultState.CURRENT)

    def _readiness_text(self, snapshot: TextSnapshot) -> str:
        if snapshot.check is SourceCheck.TOO_LONG:
            return strings.TEXT_TOO_LONG.format(count=snapshot.length, limit=MAX_SOURCE_CODE_POINTS)
        block = snapshot.readiness.translate
        draft = self.controller.draft
        if block is TranslateBlock.UNSUPPORTED:
            return strings.TEXT_UNSUPPORTED.format(
                source=self.registry.display_name(draft.source),
                target=self.registry.display_name(draft.target),
            )
        if block is TranslateBlock.PACK_MISSING:
            items = ", ".join(
                describe(item, self.registry)
                for item in snapshot.readiness.missing
                if item.kind.value == "translation"
            )
            return strings.MODE_UNAVAILABLE.format(items=items)
        if snapshot.check is SourceCheck.EMPTY:
            return strings.TEXT_EMPTY_REASON
        return ""
