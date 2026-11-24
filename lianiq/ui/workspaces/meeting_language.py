"""The Meeting *Your language* selector (CAP-0181 spec §2.2.1 step 3, §2.3, §3.4).

``MeetingWorkspace`` base (file-size split). One combo row above the table group lists the
two members of the session pair by registry English name (item data: the language ID) and
names the table language, the other member, as text. It shows the saved
``meeting.local_language`` when that is a pair member, else the pair's first member; the
session derives the same language (``local_language_id``), so a saved language outside the
pair is never used and stays saved until the PO chooses. A choice is written to
``config.meeting`` at once and saved with the settings. The selector follows the Conversation
pair control and is locked while a meeting starts, runs or drains and when no pair is ready.
"""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel

from lianiq.languages.errors import LanguageContractError
from lianiq.languages.registry import LanguageId, LanguagePair
from lianiq.ui import strings


class MeetingLanguage:
    """``MeetingWorkspace`` base: the local-language choice and the table-language text."""

    def language_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        caption = QLabel(strings.MEETING_YOUR_LANGUAGE)
        self.local_language_combo = QComboBox()
        self.local_language_combo.setAccessibleName(strings.MEETING_YOUR_LANGUAGE)
        caption.setBuddy(self.local_language_combo)
        self.table_language_label = QLabel()
        self.table_language_label.setObjectName("meetingTableLanguage")
        row.addWidget(caption)
        row.addWidget(self.local_language_combo, 1)
        row.addWidget(self.table_language_label)
        self.local_language_combo.activated.connect(self._local_language_activated)
        return row

    def session_language_pair(self) -> LanguagePair:
        return self.pipeline.registry.pair(*self.config.languages.pair)

    def local_language_id(self) -> LanguageId:
        """The saved local language if it is a pair member, else the pair's first member."""
        pair = self.session_language_pair()
        try:
            saved = self.pipeline.registry.get(self.config.meeting.local_language).id
        except LanguageContractError:
            return pair.first
        return saved if saved in pair else pair.first

    def show_local_languages(self) -> None:
        """Both pair members, the derived local language selected, the table language named."""
        registry, combo = self.pipeline.registry, self.local_language_combo
        combo.blockSignals(True)
        combo.clear()
        text = ""
        try:
            pair, local = self.session_language_pair(), self.local_language_id()
        except LanguageContractError:  # an invalid pair setting is named by the availability
            pass
        else:
            for member in pair.members:
                combo.addItem(registry.display_name(member), member)
            combo.setCurrentIndex(combo.findData(local))
            text = strings.MEETING_TABLE_LANGUAGE.format(
                language=registry.display_name(pair.other(local))
            )
        combo.blockSignals(False)
        self.table_language_label.setText(text)
        self.table_language_label.setAccessibleName(text)

    def lock_local_language(self, busy: bool) -> None:
        ready = self.host.conversation.current_pair() is not None
        self.local_language_combo.setEnabled(
            not busy and ready and self.local_language_combo.count() == 2
        )

    def _local_language_activated(self, index: int) -> None:
        self.config.meeting.local_language = self.local_language_combo.itemData(index)
        self.refresh()
