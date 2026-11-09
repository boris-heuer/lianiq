"""The shell layout and style of ``MainWindow`` (CAP-0168 file-size split)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from lianiq.ui.notice_banner import NoticeBanner
from lianiq.ui.shell.navigation import NavigationSidebar
from lianiq.ui.shell.session_strip import SessionStrip
from lianiq.ui.shell.workspaces import DEFAULT_ENTRIES, WorkspaceId


class MainWindowLayout:
    """``MainWindow`` base: the sidebar, the workspace pages, the strip and the style."""

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

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #111827; color: #e5e7eb; font-size: 14px; }
            QFrame#navigationSidebar { background: #0b1220; border-right: 1px solid #334155; }
            QFrame#navigationSidebar QToolButton { padding: 8px; border-radius: 7px;
                                                   text-align: left; }
            QFrame#navigationSidebar QToolButton:checked { background: #1e293b;
                                                           border-left: 3px solid #60a5fa;
                                                           font-weight: 700; }
            QFrame#navigationSidebar QToolButton:disabled { color: #64748b; }
            QFrame#sessionStrip { background: #1e293b; border: 1px solid #475569;
                                  border-radius: 7px; }
            QLabel#panelTitle { font-size: 17px; font-weight: 600; color: #cbd5e1; }
            QPlainTextEdit { background: #0b1220; border: 1px solid #334155; border-radius: 10px;
                             padding: 14px; font-size: 20px; selection-background-color: #2563eb; }
            QComboBox, QPushButton { background: #1e293b; border: 1px solid #475569;
                                    border-radius: 7px; padding: 8px 12px; }
            QComboBox:hover, QPushButton:hover { border-color: #60a5fa; }
            QPushButton#primaryButton { background: #2563eb; border-color: #3b82f6; font-weight: 600; }
            QPushButton:disabled { color: #64748b; background: #172033; }
            QProgressBar { background: #0b1220; border: 1px solid #334155; border-radius: 5px; }
            QProgressBar::chunk { background: #22c55e; border-radius: 4px; }
            QStatusBar { color: #94a3b8; }
            QFrame#noticeBanner { border-radius: 7px; border: 1px solid #475569;
                                  background: #1e293b; }
            QFrame#noticeBanner[severity="warning"] { border: 2px solid #f59e0b;
                                                      background: #2a2214; }
            QFrame#noticeBanner[severity="blocking"] { border: 2px solid #f87171;
                                                       background: #2a1517; }
            QLabel#noticeTitle { font-weight: 600; }
            """
        )
