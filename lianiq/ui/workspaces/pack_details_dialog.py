"""The pack details dialog (CAP-0171 spec §2.2.2, AC-07, AC-12).

It shows source, model and version, languages, sizes, free space, licence, use constraints,
the SHA-256 per file (expandable) and "Needed by". **Download** and **Import…** stay
disabled until the licence box is ticked, and while free space is below ``required_bytes``
(then ``PACK_NO_SPACE`` shows). **Import…** offers **Choose file…** (``.zip``) and **Choose
folder…**. The dialog only records the choice; the workspace starts the job.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from lianiq.packs.catalog import PackDefinition
from lianiq.packs.disk import required_bytes
from lianiq.ui import strings
from lianiq.ui.workspaces.language_packs_rows import format_size
from lianiq.ui.workspaces.settings import read_only_value


def pick_file(parent: QWidget) -> Path | None:
    path, _ = QFileDialog.getOpenFileName(parent, strings.PACK_IMPORT_FILE, "", "*.zip")
    return Path(path) if path else None


def pick_folder(parent: QWidget) -> Path | None:
    path = QFileDialog.getExistingDirectory(parent, strings.PACK_IMPORT_FOLDER)
    return Path(path) if path else None


class PackDetailsDialog(QDialog):
    """``choice`` is ``("download", None)`` or ``("import", path)`` once accepted."""

    def __init__(
        self,
        parent: QWidget,
        pack: PackDefinition,
        languages: str,
        needed: tuple[str, ...],
        free: int,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(pack.model)
        self.pack = pack
        self.choice: tuple[str, Path | None] | None = None
        self.space_ok = free >= required_bytes(pack)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        size = strings.PACK_DETAILS_SIZE.format(
            download=format_size(pack.download_bytes), installed=format_size(pack.installed_bytes)
        )
        rows = (
            (strings.PACK_DETAILS_SOURCE, f"{pack.publisher} — {pack.source_url}"),
            (strings.PACK_DETAILS_MODEL, f"{pack.model} {pack.version} ({pack.upstream_revision})"),
            (strings.PACK_DETAILS_LOCALES, languages),
            (strings.PACK_DETAILS_SIZE.split(":")[0], size),
            (strings.PACK_DETAILS_FREE, format_size(free)),
            (strings.PACK_DETAILS_LICENCE, pack.licence),
            (strings.PACK_DETAILS_CONSTRAINTS, pack.use_constraints or "—"),
            (strings.PACK_NEEDED_BY.split(":")[0], ", ".join(needed) or "—"),
        )
        self.values: dict[str, QLabel] = {}
        for caption, text in rows:
            value = read_only_value(caption)
            value.setWordWrap(True)
            value.setText(text)
            label = QLabel(caption)
            label.setBuddy(value)
            form.addRow(label, value)
            self.values[caption] = value
        layout.addLayout(form)
        self.integrity_toggle = QToolButton()
        self.integrity_toggle.setText(strings.PACK_DETAILS_INTEGRITY)
        self.integrity_toggle.setAccessibleName(strings.PACK_DETAILS_INTEGRITY)
        self.integrity_toggle.setCheckable(True)
        self.integrity_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.integrity_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.integrity = QPlainTextEdit()
        self.integrity.setReadOnly(True)
        self.integrity.setAccessibleName(strings.PACK_DETAILS_INTEGRITY)
        self.integrity.setPlainText("\n".join(f"{f.sha256}  {f.path}" for f in pack.files))
        self.integrity.setVisible(False)
        self.integrity_toggle.toggled.connect(self._toggle_integrity)
        layout.addWidget(self.integrity_toggle)
        layout.addWidget(self.integrity)
        self.space_label = QLabel(
            strings.PACK_NO_SPACE.format(
                required=format_size(required_bytes(pack)), free=format_size(free)
            )
        )
        self.space_label.setWordWrap(True)
        self.space_label.setVisible(not self.space_ok)
        layout.addWidget(self.space_label)
        accept = strings.PACK_ACCEPT_LICENCE.format(licence=pack.licence)
        self.licence_box = QCheckBox(accept)
        self.licence_box.setAccessibleName(accept)
        self.licence_box.toggled.connect(self._update_buttons)
        layout.addWidget(self.licence_box)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.download_button = QPushButton(strings.PACK_DOWNLOAD)
        self.download_button.setObjectName("primaryButton")
        self.download_button.setAccessibleName(strings.PACK_DOWNLOAD)
        self.download_button.setDefault(True)
        self.download_button.clicked.connect(lambda: self._choose("download", None))
        self.import_button = QPushButton(strings.PACK_IMPORT)
        self.import_button.setAccessibleName(strings.PACK_IMPORT)
        menu = QMenu(self.import_button)
        self.import_file_action = menu.addAction(strings.PACK_IMPORT_FILE)
        self.import_folder_action = menu.addAction(strings.PACK_IMPORT_FOLDER)
        self.import_file_action.triggered.connect(lambda: self._import(pick_file))
        self.import_folder_action.triggered.connect(lambda: self._import(pick_folder))
        self.import_button.setMenu(menu)
        role = QDialogButtonBox.ButtonRole.AcceptRole
        buttons.addButton(self.download_button, role)
        buttons.addButton(self.import_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_buttons()
        self.integrity_toggle.setFocus()

    def _toggle_integrity(self, shown: bool) -> None:
        self.integrity.setVisible(shown)
        arrow = Qt.ArrowType.DownArrow if shown else Qt.ArrowType.RightArrow
        self.integrity_toggle.setArrowType(arrow)

    def _update_buttons(self) -> None:
        allowed = self.licence_box.isChecked() and self.space_ok
        self.download_button.setEnabled(allowed)
        self.import_button.setEnabled(allowed)

    def _import(self, pick) -> None:
        path = pick(self)
        if path is not None:
            self._choose("import", path)

    def _choose(self, kind: str, path: Path | None) -> None:
        if not self.download_button.isEnabled():
            return
        self.choice = (kind, path)
        self.accept()
