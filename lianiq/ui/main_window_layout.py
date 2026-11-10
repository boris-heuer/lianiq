"""The shell layout, Tab order and opening size of ``MainWindow`` (CAP-0168 file-size split)."""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from lianiq.ui.notice_banner import NoticeBanner
from lianiq.ui.shell import focus
from lianiq.ui.shell.navigation import NavigationSidebar
from lianiq.ui.shell.scroll import scroll_area_of
from lianiq.ui.shell.session_strip import SessionStrip
from lianiq.ui.shell.workspaces import DEFAULT_ENTRIES, WorkspaceId


class MainWindowLayout:
    """``MainWindow`` base: the sidebar, the workspace pages, the strip and the Tab order."""

    def _build_ui(self) -> None:
        root = QWidget()
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.navigation = NavigationSidebar(DEFAULT_ENTRIES)
        row.addWidget(self.navigation)
        column = QVBoxLayout()
        column.setContentsMargins(20, 16, 20, 12)
        column.setSpacing(10)
        row.addLayout(column, 1)

        # The strip exists first: the held-turn bar returns focus to its **Stop**.
        self.session_strip = SessionStrip()
        self.session_strip.stop_button.clicked.connect(self.stop_active_session)
        self.pages = QStackedWidget()
        conversation_page = QWidget()
        conversation_page.setObjectName("conversationPage")
        conversation_layout = QVBoxLayout(conversation_page)
        conversation_layout.setContentsMargins(0, 0, 0, 0)
        conversation_layout.setSpacing(10)
        self.conversation.build(conversation_layout)
        self.workspace_pages = {
            WorkspaceId.CONVERSATION: conversation_page,
            WorkspaceId.CALL_BRIDGE: self.call_bridge.build_page(),
            WorkspaceId.SETTINGS: self.settings.build_page(),
        }
        for page in self.workspace_pages.values():
            self.pages.addWidget(page)
        column.addWidget(self.pages, 1)
        column.addWidget(self.session_strip)
        # A notice banner at the top of each workspace page.
        self.banners: dict[WorkspaceId, NoticeBanner] = {}
        for workspace, page in self.workspace_pages.items():
            banner = NoticeBanner(self.notices, workspace)
            # Focus inside a banner that hides goes to that workspace's sidebar entry.
            banner.focus_fallback = lambda workspace=workspace: self.navigation.buttons[workspace]
            banner.more_requested.connect(self.show_diagnostics)
            page.layout().insertWidget(0, banner)
            self.banners[workspace] = banner
        self.navigation.workspace_selected.connect(self.show_workspace)
        self.navigation.select(WorkspaceId.CONVERSATION, notify=False)
        self.session_owner.subscribe(self._session_changed)
        self.diagnostics.record(
            "models", f"Speech recognition model: {self.config.speech_to_text.model_path}"
        )

        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Models load when the first speech segment is processed.")

    def _load_devices(self) -> None:
        # A failed device enumeration is reported once; the endpoints are then not listed.
        if self.device_setup.load():
            self.call_bridge.load_endpoints()

    # The look is ``theme.apply`` (CAP-0168 WI-05), which replaced ``_apply_style``.

    def focus_regions(self) -> tuple[QWidget, ...]:
        """The Tab order regions: sidebar → shown workspace → session strip (AC-28)."""
        return (self.navigation, self.pages.currentWidget(), self.session_strip)

    def focusNextPrevChild(self, next: bool) -> bool:
        built = getattr(self, "session_strip", None) is not None and hasattr(self, "pages")
        target = focus.step(self, self.focus_regions(), next) if built else None
        if target is None:
            return super().focusNextPrevChild(next)
        reason = Qt.FocusReason.TabFocusReason if next else Qt.FocusReason.BacktabFocusReason
        target.setFocus(reason)
        area = scroll_area_of(target)
        if area is not None:
            area.ensureWidgetVisible(target)
        return True

    def fit_to_work_area(self, available: QRect) -> None:
        """Open at the default size, or the largest that fits ``available`` (spec §2.2.1).

        Below the minimum size the minimum yields to the work area; the workspaces then
        scroll, with Start/Stop and the session strip outside the scroll areas.
        """
        frame = self.frameGeometry().size() - self.geometry().size()
        width = min(self.default_size[0], available.width() - frame.width())
        height = min(self.default_size[1], available.height() - frame.height())
        self.setMinimumSize(min(self.minimum_size[0], width), min(self.minimum_size[1], height))
        self.resize(width, height)
        left = available.left() + max(0, (available.width() - width - frame.width()) // 2)
        top = available.top() + max(0, (available.height() - height - frame.height()) // 2)
        self.move(left, top)
