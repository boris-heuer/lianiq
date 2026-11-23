"""Setup assistant step 4, *Readiness* (CAP-0171 spec §2.2.1 item 5, AC-05; C §7).

The WI-03 ``readiness_review`` of the ticked usages: one row per pack, then one per device
role, each with *Ready* or the reason and "Needed by" (or *Optional — for spoken output*).
A pack row that is not ready has one **Get…**, which opens the WI-04 details dialog and job.
The header shows ``ASSIST_REVIEW_SPACE``. ``compute_review`` may hash pack files, so the
assistant runs it off the Qt thread; rows are told apart by requirement kind (C §7).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from lianiq.languages.capabilities import CapabilityCatalog, ReadinessProbe
from lianiq.languages.registry import LanguagePair, LanguageRegistry
from lianiq.languages.requirements import DeviceReadiness, describe
from lianiq.packs.errors import ManifestError
from lianiq.packs.manifest import Manifest
from lianiq.packs.state import readiness_pack_files
from lianiq.packs.usage import (
    ReadinessReview,
    ReviewRow,
    ReviewStatus,
    UsageProfile,
    is_device_row,
    readiness_review,
)
from lianiq.ui import strings
from lianiq.ui.workspaces import language_packs as packs_page
from lianiq.ui.workspaces.language_packs_rows import format_size, sentence

STATUS_TEXT = {
    ReviewStatus.READY: strings.ASSIST_REVIEW_READY,
    ReviewStatus.NOT_INSTALLED: strings.ASSIST_REVIEW_NOT_INSTALLED,
    ReviewStatus.FILES_MISSING: strings.ASSIST_REVIEW_FILES_MISSING,
    ReviewStatus.INVALID: strings.ASSIST_REVIEW_INVALID,
    ReviewStatus.DEVICE_NOT_FOUND: strings.ASSIST_REVIEW_DEVICE,
}


def device_readiness(host) -> DeviceReadiness:
    """The Conversation, Call Bridge and Meeting device state (read on the Qt thread)."""
    conversation = host.device_readiness()
    return DeviceReadiness(
        microphone=conversation.microphone,
        playback=conversation.playback,
        call_endpoints=frozenset(role.value for role in host.call_bridge_panel.assigned_roles()),
        meeting_endpoints=host.meeting.device_readiness().meeting_endpoints,
    )


def compute_review(
    host, usages: Sequence[UsageProfile], pair: LanguagePair, devices: DeviceReadiness
) -> ReadinessReview:
    """The review against the pack files on disk, as the Language packs page probes them."""
    page, config = host.language_packs, host.config
    try:
        manifest = Manifest.read(page.manifest_path)
    except ManifestError:
        manifest = Manifest()
    pack_files = readiness_pack_files(page.packs, manifest, config, page.root)
    probe = ReadinessProbe(page.root, page.manifest_path, pack_files=pack_files)
    catalog = CapabilityCatalog.from_config(config, page.registry, probe)
    free = packs_page.free_bytes(page.models)
    return readiness_review(usages, pair, config, catalog, page.packs, devices, free)


def row_text(row: ReviewRow, registry: LanguageRegistry, local_language: str) -> str:
    names = ", ".join(
        describe(item, registry, local_language=local_language) for item in row.requirements
    )
    if row.optional:
        tail = strings.ASSIST_OPTIONAL_VOICE
    else:
        tail = strings.PACK_NEEDED_BY.format(usages=", ".join(row.needed_by))
    return f"{sentence(names)} — {STATUS_TEXT[row.status]} — {tail}"


class ReviewStep(QWidget):
    def __init__(self, registry: LanguageRegistry, get: Callable[[str], object]) -> None:
        super().__init__()
        self.registry, self.get = registry, get
        layout = QVBoxLayout(self)
        title = QLabel(strings.ASSIST_REVIEW_TITLE)
        title.setObjectName("panelTitle")
        layout.addWidget(title)
        self.space = QLabel(strings.PACK_STATE_CHECKING)
        self.space.setWordWrap(True)
        self.space.setAccessibleName(self.space.text())
        layout.addWidget(self.space)
        self.list = QVBoxLayout()
        layout.addLayout(self.list)
        layout.addStretch(1)
        self.review: ReadinessReview | None = None
        self.row_labels: list[QLabel] = []
        self.get_buttons: dict[str, QPushButton] = {}

    def clear(self) -> None:
        self.review = None
        self.space.setText(strings.PACK_STATE_CHECKING)
        self.space.setAccessibleName(self.space.text())
        while self.list.count():
            self.list.takeAt(0).widget().deleteLater()
        self.row_labels, self.get_buttons = [], {}

    def show_review(self, review: ReadinessReview, local_language: str) -> None:
        self.clear()
        self.review = review
        space = strings.ASSIST_REVIEW_SPACE.format(
            missing=format_size(review.missing_bytes), free=format_size(review.free_bytes)
        )
        self.space.setText(space)
        self.space.setAccessibleName(space)
        for row in review.rows:
            line = QWidget()
            columns = QHBoxLayout(line)
            columns.setContentsMargins(0, 0, 0, 0)
            label = QLabel(row_text(row, self.registry, local_language))
            label.setWordWrap(True)
            label.setAccessibleName(label.text())
            columns.addWidget(label, 1)
            self.row_labels.append(label)
            pack_id = row.pack_id
            if (
                not is_device_row(row)
                and pack_id is not None
                and row.status is not ReviewStatus.READY
            ):
                button = QPushButton(strings.PACK_GET)
                button.setAccessibleName(strings.PACK_GET)
                button.setAccessibleDescription(label.text())
                button.clicked.connect(lambda _=False, pack_id=pack_id: self.get(pack_id))
                columns.addWidget(button)
                self.get_buttons[pack_id] = button
            self.list.addWidget(line)
