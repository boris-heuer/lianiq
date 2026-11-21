"""Pack rows of the Language packs workspace and their texts (CAP-0171 spec §2.3, C §11).

A row shows name, languages, size, a state chip in text (never colour alone), "Needed by"
and one primary action (*Get…*, *Update…*, *Download again*) plus **Remove** for an
installed pack; during its job the progress bar with **Cancel**, after a failure the reason
with **Retry**. A *Custom path* row shows the CAP-0169 status only.
"""

from __future__ import annotations

from collections.abc import Callable
from itertools import combinations

from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton

from lianiq.languages.capabilities import CapabilityCatalog, DirectedEdge, ReadinessStatus
from lianiq.languages.modes import (
    CALL_BRIDGE_MODE,
    MEETING_MODE,
    InputKind,
    OutputKind,
    RoutingKind,
    SessionPair,
    UsageMode,
)
from lianiq.languages.registry import Availability, LanguageId, LanguageRegistry
from lianiq.languages.requirements import requirements
from lianiq.packs.catalog import PackCatalog, PackDefinition, PackKind
from lianiq.packs.errors import (
    ConnectionUnavailable,
    InsufficientSpace,
    JobBusy,
    PackFileError,
    PackInUse,
)
from lianiq.packs.installer import FILES_IN_USE
from lianiq.packs.jobs import JobPhase, JobView, failure_reason
from lianiq.packs.state import PackState, PackStatus
from lianiq.ui import strings

STATE_TEXT = {
    PackState.PLANNED: strings.PACK_STATE_PLANNED,
    PackState.UNSUPPORTED: strings.PACK_STATE_UNSUPPORTED,
    PackState.DOWNLOADABLE: strings.PACK_STATE_DOWNLOADABLE,
    PackState.INSTALLING: strings.PACK_STATE_INSTALLING,
    PackState.INSTALLED: strings.PACK_STATE_INSTALLED,
    PackState.VALIDATED: strings.PACK_STATE_VALIDATED,
    PackState.FAILED: strings.PACK_STATE_FAILED,
}
TEXT_MODE = UsageMode(InputKind.MICROPHONE, RoutingKind.BIDIRECTIONAL, OutputKind.TEXT)
Sessions = dict[str, tuple[SessionPair, ...]]


def format_size(size: int) -> str:
    for unit, scale in (("GB", 10**9), ("MB", 10**6), ("KB", 10**3)):
        if size >= scale:
            value = size / scale
            return f"{value:.1f} {unit}" if unit == "GB" else f"{round(value)} {unit}"
    return f"{size} bytes"


def sentence(text: str) -> str:
    return text[:1].upper() + text[1:]


def pack_languages(pack: PackDefinition, registry: LanguageRegistry) -> str:
    def name(subject: str) -> str:
        if pack.kind is PackKind.TRANSLATION:
            edge = DirectedEdge.from_key(subject)
            return strings.ROUTING_FIXED.format(
                source=registry.get(edge.source).english_name,
                target=registry.get(edge.target).english_name,
            )
        return registry.get(subject).english_name

    return ", ".join(name(subject) for subject in pack.provides)


def profile_sessions(registry: LanguageRegistry) -> Sessions:
    """The sessions of every enabled or experimental usage over the qualified pairs.

    Conversation counts in text mode: its voices are optional (spoken output only).
    """
    qualified = [d.id for d in registry.languages() if d.availability is Availability.QUALIFIED]
    pairs = [registry.pair(a, b) for a, b in combinations(qualified, 2)]

    def local(mode: UsageMode) -> tuple[SessionPair, ...]:
        return tuple(SessionPair(p, mode, local_language=lang) for p in pairs for lang in p.members)

    return {
        strings.USAGE_CONVERSATION: tuple(SessionPair(p, TEXT_MODE) for p in pairs),
        strings.USAGE_CALL_BRIDGE: local(CALL_BRIDGE_MODE),
        strings.USAGE_MEETING: local(MEETING_MODE),
    }


def session_packs(session: SessionPair, packs: PackCatalog) -> frozenset[str]:
    found = (packs.for_requirement(item) for item in requirements(session))
    return frozenset(pack.id for pack in found if pack is not None)


def needed_by(pack_id: str, packs: PackCatalog, sessions: Sessions) -> tuple[str, ...]:
    return tuple(
        usage
        for usage, items in sessions.items()
        if any(pack_id in session_packs(session, packs) for session in items)
    )


def broken_usages(
    pack_id: str, packs: PackCatalog, sessions: Sessions, ready: frozenset[str]
) -> tuple[str, ...]:
    """Usages with a session whose packs are all ready now and that needs ``pack_id``."""
    return tuple(
        usage
        for usage, items in sessions.items()
        if any(pack_id in (used := session_packs(s, packs)) and used <= ready for s in items)
    )


def capability_text(catalog: CapabilityCatalog, pack: PackDefinition) -> str:
    """The CAP-0169 status of a *Custom path* pack, e.g. "Custom path — validated"."""

    def status(subject: str) -> ReadinessStatus:
        if pack.kind is PackKind.RECOGNITION:
            return catalog.recognition(LanguageId(subject)).status
        if pack.kind is PackKind.TRANSLATION:
            return catalog.translation(DirectedEdge.from_key(subject)).status
        return catalog.voice(LanguageId(subject)).status

    values = sorted({status(subject).value for subject in pack.provides})
    return f"{strings.PACK_CUSTOM_PATH} — {', '.join(values)}"


def error_text(error: BaseException | None, reason: str) -> str:
    """The row message of a refused or failed job (C §11)."""
    if isinstance(error, ConnectionUnavailable):
        return strings.PACK_DOWNLOAD_UNAVAILABLE.format(host=error.host)
    if isinstance(error, InsufficientSpace):
        return strings.PACK_NO_SPACE.format(
            required=format_size(error.required), free=format_size(error.free)
        )
    if isinstance(error, JobBusy):
        return strings.PACK_BUSY
    if isinstance(error, PackInUse):
        return strings.PACK_IN_USE.format(mode=error.mode)
    if isinstance(error, PackFileError):
        return strings.PACK_IMPORT_REJECTED.format(reason=error.reason)
    if error is not None and reason == FILES_IN_USE:
        return strings.PACK_FILES_IN_USE
    return sentence(reason if error is None else failure_reason(error))


def progress_text(view: JobView) -> str:
    if view.phase is JobPhase.TRANSFER and view.total:
        return strings.PACK_PROGRESS_BYTES.format(
            done=format_size(view.done), total=format_size(view.total)
        )
    if view.phase is JobPhase.CHECK:
        return strings.PACK_CHECKING.format(done=view.done, count=view.total)
    return strings.PACK_STATE_INSTALLING


def _button(text: str, handler: Callable[[], None]) -> QPushButton:
    button = QPushButton(text)
    button.setAccessibleName(text)
    button.clicked.connect(handler)
    return button


class PackRow(QFrame):
    """One catalog pack; ``actions`` maps "primary", "remove", "import", "retry", "cancel"."""

    def __init__(
        self, pack: PackDefinition, languages: str, needed: tuple[str, ...], actions
    ) -> None:
        super().__init__()
        self.setObjectName("packRow")
        self.pack, self.name = pack, pack.model
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 4, 0, 4)
        title = QLabel(f"{self.name} {pack.version}")
        title.setObjectName("noticeTitle")  # the theme's semibold label
        size = strings.PACK_DETAILS_SIZE.format(
            download=format_size(pack.download_bytes), installed=format_size(pack.installed_bytes)
        )
        usages = ", ".join(needed) if needed else "—"
        details = QLabel(f"{languages} · {size} · {strings.PACK_NEEDED_BY.format(usages=usages)}")
        details.setWordWrap(True)
        self.state_label = QLabel()
        self.message_label = QLabel()
        self.message_label.setWordWrap(True)
        self.progress_label = QLabel()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setAccessibleName(f"{self.name} progress")
        grid.addWidget(title, 0, 0)
        grid.addWidget(self.state_label, 0, 1)
        grid.addWidget(details, 1, 0, 1, 2)
        grid.addWidget(self.progress, 2, 0)
        grid.addWidget(self.progress_label, 2, 1)
        grid.addWidget(self.message_label, 3, 0, 1, 2)
        buttons = QHBoxLayout()
        self.primary_button = _button(strings.PACK_GET, actions["primary"])
        self.remove_button = _button(strings.PACK_REMOVE, actions["remove"])
        self.import_button = _button(strings.PACK_IMPORT, actions["import"])
        self.retry_button = _button(strings.PACK_RETRY, actions["retry"])
        self.cancel_button = _button(strings.PACK_CANCEL, actions["cancel"])
        self.job_buttons = (self.primary_button, self.remove_button, self.import_button)
        for button in (*self.job_buttons, self.retry_button, self.cancel_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        grid.addLayout(buttons, 4, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        self.status: PackStatus | None = None
        self.show_unknown(strings.PACK_STATE_CHECKING)

    def show_unknown(self, text: str) -> None:
        """No status snapshot (yet): a neutral state text and no actions at all."""
        self.status = None
        self.state_label.setText(text)
        self.setAccessibleName(f"{self.name}, {text}")
        for widget in (*self.job_buttons, self.retry_button, self.cancel_button, self.progress):
            widget.setVisible(False)
        self.progress_label.setVisible(False)
        self.message_label.setVisible(False)

    @property
    def state_text(self) -> str:
        return self.state_label.text()

    def show_status(
        self,
        status: PackStatus,
        view: JobView | None = None,
        *,
        message: str = "",
        offline: bool = False,
        custom: str = "",
        installed: str = "",
    ) -> None:
        """``message``: the last job's failure; ``offline``: it found no connection;
        ``custom``: the *Custom path* text; ``installed``: the recorded version."""
        self.status = status
        state, running = status.state, view is not None
        text = custom or STATE_TEXT[state]
        if status.update_available and not custom and not running:
            text += " · " + strings.PACK_UPDATE_AVAILABLE.format(
                installed=installed, offered=self.pack.version
            )
        self.state_label.setText(text)
        self.setAccessibleName(f"{self.name}, {text}")
        primary = {
            PackState.DOWNLOADABLE: strings.PACK_GET,
            PackState.FAILED: strings.PACK_REDOWNLOAD,
        }.get(state, strings.PACK_UPDATE if status.update_available else "")
        job_failed = bool(message)
        if state is PackState.FAILED and status.reason and not message:
            message = strings.PACK_FAILED_RECOVER.format(reason=sentence(status.reason))
        idle = not custom and not running
        self.primary_button.setText(primary or strings.PACK_GET)
        self.primary_button.setAccessibleName(self.primary_button.text())
        self.primary_button.setVisible(bool(primary) and idle)
        installed_state = state in (PackState.INSTALLED, PackState.VALIDATED, PackState.FAILED)
        self.remove_button.setVisible(installed_state and idle)
        self.import_button.setVisible((offline or state is PackState.FAILED) and idle)
        self.retry_button.setVisible(job_failed and idle)
        self.cancel_button.setVisible(running)
        self.progress.setVisible(running)
        self.progress_label.setVisible(running)
        self.message_label.setText(message)
        self.message_label.setVisible(bool(message))
        if view is not None:
            self.progress.setValue(view.done * 1000 // view.total if view.total else 0)
            self.progress_label.setText(progress_text(view))

    def set_busy(self, busy: bool) -> None:
        """Another pack's job runs: every job action is disabled with ``PACK_BUSY``."""
        tip = strings.PACK_BUSY if busy else ""
        for button in (*self.job_buttons, self.retry_button):
            button.setEnabled(not busy)
            button.setToolTip(tip)
            button.setAccessibleDescription(tip)
