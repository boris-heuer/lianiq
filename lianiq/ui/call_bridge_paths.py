"""One Call Bridge path box: **You → call** or **Call → you** (CAP-0166 spec §2.3).

``CallPathBox`` holds the two endpoint selectors of its path (full Windows display names,
filtered by flow), the level meter of its capture endpoint, the lane status line, the
route-test row and the collapsible call-app help. It only shows state: the workspace owns
the route-test book and the readiness evaluation. Each widget sets its own accessible name.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Mapping

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
)

from lianiq.call_bridge.contracts import (
    EXPECTED_ENDPOINT_FLOWS,
    AudioEndpointRef,
    LaneId,
)
from lianiq.call_bridge.route_tests import PATH_ROLES, RouteTestState
from lianiq.ui import strings_call_bridge as s

NO_SIGNAL_MS = 5_000
SIGNAL_LEVEL = 0.05  # meter level (0..1) that counts as signal
CLIP_HOLD_S = 1.0  # "Too loud" stays this long after the last clipped block
PATH_NAMES = {LaneId.OUTBOUND: s.CB_PATH_OUT_NAME, LaneId.INBOUND: s.CB_PATH_IN_NAME}
_IDLE_TESTS = frozenset(
    {
        RouteTestState.NOT_TESTED,
        RouteTestState.PASSED,
        RouteTestState.FAILED,
        RouteTestState.CANCELLED,
        RouteTestState.PLAY_ERROR,
    }
)


def route_test_text(path: LaneId, state: RouteTestState, detail: str) -> str:
    """The route-test row text of ``state``; never a lane activity such as *Running*."""
    if state is RouteTestState.AWAITING_ANSWER:
        return s.CB_Q_OUT if path is LaneId.OUTBOUND else s.CB_Q_IN
    if state is RouteTestState.FAILED:
        return s.CB_T_FAILED.format(setting=detail)
    if state is RouteTestState.PLAY_ERROR:
        return s.CB_T_PLAY_ERROR.format(reason=detail)
    return {
        RouteTestState.NOT_TESTED: s.CB_T_NOT_TESTED,
        RouteTestState.PLAYING: s.CB_T_PLAYING,
        RouteTestState.PASSED: s.CB_T_PASSED,
        RouteTestState.CANCELLED: s.CB_T_CANCELLED,
    }[state]


class CallPathBox(QGroupBox):
    selection_changed = Signal()
    test_requested = Signal(object)  # LaneId
    cancel_requested = Signal(object)
    answered = Signal(object, bool)  # LaneId, the partner (or you) heard it

    def __init__(self, path: LaneId) -> None:
        super().__init__()
        self.path = path
        self.capture_role, self.render_role = PATH_ROLES[path]
        self.combos: dict = {}
        self._stale: dict = {}  # persisted IDs not in the inventory, until changed
        self._populating = False
        self._stream_open = False
        self._clip_until = 0.0
        outbound = path is LaneId.OUTBOUND
        self._level_name = s.CB_LEVEL_MIC if outbound else s.CB_LEVEL_CALL
        self._hint = s.CB_HINT_MIC if outbound else s.CB_HINT_CALL
        grid = QGridLayout(self)
        for row, role in enumerate((self.capture_role, self.render_role)):
            label = QLabel(s.CB_ROLE_LABELS[role])
            combo = QComboBox()
            combo.setMinimumContentsLength(28)
            combo.setAccessibleName(s.CB_ROLE_LABELS[role])
            combo.currentIndexChanged.connect(lambda _i, role=role: self._combo_changed(role))
            label.setBuddy(combo)
            self.combos[role] = combo
            grid.addWidget(label, row * 2, 0, 1, 3)
            grid.addWidget(combo, row * 2 + 1, 0, 1, 3)
        self.level_label = QLabel(self._level_name)
        self.level_bar = QProgressBar()
        self.level_bar.setRange(0, 100)
        self.level_bar.setTextVisible(False)
        self.level_bar.setValue(0)
        self.level_bar.setAccessibleName(self._level_name)
        self.level_label.setBuddy(self.level_bar)
        self.level_caption = QLabel()
        grid.addWidget(self.level_label, 4, 0)
        grid.addWidget(self.level_bar, 4, 1)
        grid.addWidget(self.level_caption, 4, 2)
        self.status_label = QLabel()
        grid.addWidget(self.status_label, 5, 0, 1, 3)
        grid.addLayout(self._build_test_row(), 6, 0, 1, 3)
        self.test_hint = QLabel()
        self.test_hint.setWordWrap(True)
        self.test_hint.hide()
        grid.addWidget(self.test_hint, 7, 0, 1, 3)
        self.help_toggle = QPushButton()
        self.help_toggle.setText(s.CB_HELP_TITLE)
        self.help_toggle.setAccessibleName(s.CB_HELP_TITLE)
        self.help_toggle.setCheckable(True)
        self.help_label = QLabel(s.CB_HELP_OUT if outbound else s.CB_HELP_IN)
        self.help_label.setWordWrap(True)
        self.help_label.setAccessibleName(self.help_label.text())
        self.help_label.hide()
        self.help_toggle.toggled.connect(self.help_label.setVisible)
        grid.addWidget(self.help_toggle, 8, 0, 1, 3)
        grid.addWidget(self.help_label, 9, 0, 1, 3)
        grid.setColumnStretch(1, 1)
        self.no_signal_timer = QTimer(self)
        self.no_signal_timer.setSingleShot(True)
        self.no_signal_timer.setInterval(NO_SIGNAL_MS)
        self.no_signal_timer.timeout.connect(self._no_signal)
        self._set_caption("")
        self.set_lane_status(s.CB_LANE_STOPPED)
        self.show_test(RouteTestState.NOT_TESTED, "", "")

    def _build_test_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.test_status = QLabel()
        row.addWidget(self.test_status, 1)
        name = PATH_NAMES[self.path]
        self.test_button = self._button(s.CB_TEST, name, row)
        self.test_button.clicked.connect(lambda: self.test_requested.emit(self.path))
        self.cancel_button = self._button(s.CB_CANCEL, name, row)
        self.cancel_button.clicked.connect(lambda: self.cancel_requested.emit(self.path))
        self.yes_button = self._button(s.CB_YES, name, row)
        self.yes_button.clicked.connect(lambda: self.answered.emit(self.path, True))
        self.no_button = self._button(s.CB_NO, name, row)
        self.no_button.clicked.connect(lambda: self.answered.emit(self.path, False))
        return row

    @staticmethod
    def _button(text: str, path_name: str, row: QHBoxLayout) -> QPushButton:
        button = QPushButton(text)
        button.setAccessibleName(f"{text} · {path_name}")
        row.addWidget(button)
        return button

    def set_languages(self, local: str, remote: str) -> None:
        template = s.CB_PATH_OUT if self.path is LaneId.OUTBOUND else s.CB_PATH_IN
        self.setTitle(template.format(local=local, remote=remote))
        self.setAccessibleName(self.title())

    def set_endpoints(
        self, endpoints: Iterable[AudioEndpointRef], configured: Mapping[object, str | None]
    ) -> None:
        """List each role's endpoints of its flow; preselect the persisted IDs."""
        endpoints = tuple(endpoints)
        known = {endpoint.endpoint_id for endpoint in endpoints}
        self._populating = True
        try:
            for role, combo in self.combos.items():
                combo.clear()
                combo.addItem(s.CB_SELECT, None)
                for endpoint in endpoints:
                    if endpoint.flow is EXPECTED_ENDPOINT_FLOWS[role]:
                        combo.addItem(endpoint.display_name, endpoint.endpoint_id)
                wanted = configured.get(role)
                combo.setCurrentIndex(max(combo.findData(wanted), 0) if wanted else 0)
                if wanted and wanted not in known:
                    self._stale[role] = wanted
                else:
                    self._stale.pop(role, None)
        finally:
            self._populating = False
        self.selection_changed.emit()

    def selected_ids(self) -> dict:
        """Each role's selected endpoint ID; a persisted ID that is not listed stays named."""
        return {
            role: combo.currentData() or self._stale.get(role)
            for role, combo in self.combos.items()
        }

    def _combo_changed(self, role) -> None:
        if self._populating:
            return
        self._stale.pop(role, None)
        self.selection_changed.emit()

    def set_selectors_enabled(self, enabled: bool) -> None:
        for combo in self.combos.values():
            combo.setEnabled(enabled)

    def set_lane_status(self, text: str) -> None:
        """The accessible name changes with the text, so it is announced; focus stays."""
        if text == self.status_label.text():
            return
        self.status_label.setText(text)
        self.status_label.setAccessibleName(f"{s.CB_LANE_STATUS}: {text}")

    # Level meter ---------------------------------------------------------------------

    def set_stream_open(self, stream_open: bool) -> None:
        """The meter and its no-signal timer run only while the capture stream is open."""
        self._stream_open = stream_open
        self._clip_until = 0.0
        self.level_bar.setValue(0)
        self._set_caption("")
        if stream_open:
            self.no_signal_timer.start()
        else:
            self.no_signal_timer.stop()

    def set_level(self, level: float) -> None:
        if not self._stream_open:
            return
        self.level_bar.setValue(round(max(0.0, min(level, 1.0)) * 100))
        if level >= SIGNAL_LEVEL:
            self.no_signal_timer.start()
            if time.monotonic() >= self._clip_until:
                self._set_caption(s.CB_LEVEL_SIGNAL)

    def set_clipping(self) -> None:
        if self._stream_open:
            self._clip_until = time.monotonic() + CLIP_HOLD_S
            self.no_signal_timer.start()
            self._set_caption(s.CB_LEVEL_CLIPPING)

    def _no_signal(self) -> None:
        if self._stream_open:
            self._set_caption(s.CB_LEVEL_NO_SIGNAL.format(hint=self._hint))

    def _set_caption(self, text: str) -> None:
        self.level_caption.setText(text)
        self.level_caption.setAccessibleName(f"{self._level_name}: {text}".rstrip(": "))

    # Route-test row ------------------------------------------------------------------

    def show_test(self, state: RouteTestState, detail: str, blocked: str) -> None:
        """Show the row for ``state``; ``blocked`` disables **Test** and says why."""
        text = route_test_text(self.path, state, detail)
        self.test_status.setText(text)
        self.test_status.setAccessibleName(f"{s.CB_TEST_ROW}: {text}")
        idle = state in _IDLE_TESTS
        self.test_button.setVisible(idle)
        self.test_button.setEnabled(idle and not blocked)
        self.test_button.setToolTip(blocked)
        self.test_button.setAccessibleDescription(blocked)
        self.cancel_button.setVisible(state is RouteTestState.PLAYING)
        asking = state is RouteTestState.AWAITING_ANSWER
        self.yes_button.setVisible(asking)
        self.no_button.setVisible(asking)
        self.test_hint.setText(blocked if idle else "")
        self.test_hint.setAccessibleName(self.test_hint.text())
        self.test_hint.setVisible(idle and bool(blocked))
