"""Import a language pack from a folder through the real UI (spec §2.1.2; CAP-0171 E-08).

Sources are the image's read-only pack folders (``models_dir`` + the catalog ``root``
without ``models/``), the VM's "USB stick". An import needs ``lianiq-pack.json`` in the
source root; images built before lianiq#170 lack it, so ``start_import`` then returns
``PACK_FILE_MISSING`` ("image-packs-without-pack-file") before touching the UI and the row is
``blocked`` with that reason. ``make_corrupt_copy`` copies a pack folder and flips one byte in
its largest file.

``import_folder`` drives Language packs › the pack row's **Get…** (or **Import…** when the row
offers it; both only open the details dialog) › the licence box › **Import…** › **Choose
folder…** (``QFileDialog.getExistingDirectory``), types the folder path into the native folder
picker's name field without Enter (Enter navigates into the folder) and presses its **Select
Folder** button (``AutomationId`` 1). Then it waits for the row's state. Row names are
"{model}, {state}" (``strings_packs``). **Download** is never pressed, so no helper here makes
a network attempt (it would count against S-04). Every failure is a named reason; no step is
retried. The models junction must point at a writable scratch folder (``models_swap``).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from native_e2e import models_swap
from native_e2e.rows import ui
from native_e2e.uia import Node

if TYPE_CHECKING:
    from native_e2e.context import RunContext

PACK_FILE = "lianiq-pack.json"
CORRUPT_PACK = "mt-de-zh-hans"  # spec §2.1.2: the corrupt copy is of this pack
# The folder dialog's name field: the save dialog's ids (E-10) and the folder picker's.
NAME_FIELDS = ("1001", "1148", "1152")
CONFIRM_BUTTON = "1"  # IDOK: "Select Folder"
PACK_FILE_MISSING = "image-packs-without-pack-file"  # a blocked reason, not a failure


def catalog() -> Any:
    from lianiq.languages import BUILTIN_REGISTRY
    from lianiq.packs.catalog import BUILTIN_CATALOG_PATH, PackCatalog

    return PackCatalog.load(BUILTIN_CATALOG_PATH, BUILTIN_REGISTRY)


def pack(pack_id: str) -> Any:
    return catalog().get(pack_id)


def image_pack_dir(ctx: RunContext, pack_id: str) -> Path:
    """The read-only folder of ``pack_id`` in the image models."""
    root = pack(pack_id).root.removeprefix("models/")
    return models_swap.image_models(ctx).joinpath(*root.split("/"))


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)  # content only: no read-only attribute or ACL


def has_pack_file(folder: Path) -> bool:
    return (folder / PACK_FILE).is_file()


def make_corrupt_copy(src_pack_dir: Path, dst: Path) -> Path:
    """Copy ``src_pack_dir`` to ``dst`` and flip one byte in the middle of its largest file
    (never the pack file). Returns the changed file."""
    shutil.rmtree(dst, ignore_errors=True)
    files = [path for path in src_pack_dir.rglob("*") if path.is_file()]
    for path in files:
        _copy_file(path, dst / path.relative_to(src_pack_dir))
    candidates = [path for path in files if path.name != PACK_FILE]
    largest = dst / max(candidates, key=lambda path: path.stat().st_size).relative_to(src_pack_dir)
    size = largest.stat().st_size
    with largest.open("r+b") as handle:
        handle.seek(size // 2)
        byte = handle.read(1)
        handle.seek(size // 2)
        handle.write(bytes([byte[0] ^ 0xFF]))
    return largest


def row_state(nodes: list[Node], model: str) -> str | None:
    """The state text of the pack row of ``model`` ("{model}, {state}"), if shown."""
    prefix = f"{model}, "
    row = next((n for n in nodes if n.visible and n.name.startswith(prefix)), None)
    return row.name[len(prefix) :] if row is not None else None


def _row_button(nodes: list[Node], model: str, labels: tuple[str, ...]) -> Node | None:
    prefix = f"{model}, "
    for label in labels:
        for node in nodes:
            in_row = any(parent.startswith(prefix) for parent in node.parents)
            shown = node.visible and node.enabled and node.control_type == "Button"
            if in_row and shown and node.name == label:
                return node
    return None


def _field(nodes: list[Node] | None) -> Node | None:
    return next(
        (n for n in nodes or () if n.automation_id in NAME_FIELDS and n.control_type == "Edit"),
        None,
    )


def _by_id(nodes: list[Node] | None, automation_id: str) -> Node | None:
    return next(
        (n for n in nodes or () if n.automation_id == automation_id and n.control_type == "Button"),
        None,
    )


def _open_details(app: Any, s: Any, model: str) -> str | None:
    if not ui.select(app, s.NAV_LANGUAGE_PACKS, s.NAV_REGION):
        return "packs-page-not-shown"
    labels = (s.PACK_GET, s.PACK_IMPORT, s.PACK_REDOWNLOAD, s.PACK_UPDATE)
    try:
        button = ui.wait_nodes(app, lambda nodes: _row_button(nodes, model, labels))
    except TimeoutError:
        return "row-action-not-shown"
    app.press(button)
    try:
        ui.wait(lambda: app.window_nodes(model))
    except TimeoutError:
        return "details-not-opened"
    return None


def _accept_licence(app: Any, s: Any, definition: Any) -> str | None:
    label = s.PACK_ACCEPT_LICENCE.format(licence=definition.licence)

    def box(nodes: list[Node] | None) -> Node | None:
        return ui.find(nodes or (), label, "CheckBox")

    try:
        found = ui.wait(lambda: box(app.window_nodes(definition.model)))
        if not found.selected:
            app.press(found)
        ui.wait(lambda: (box(app.window_nodes(definition.model)) or found).selected)
    except TimeoutError:
        return "licence-not-accepted"
    return None


def _choose_folder(app: Any, s: Any, model: str, folder: Path) -> str | None:
    try:
        button = ui.wait(lambda: ui.find(app.window_nodes(model) or (), s.PACK_IMPORT, "Button"))
        app.press(button)
        item = ui.wait(lambda: ui.find(app.popup_nodes(), s.PACK_IMPORT_FOLDER, "MenuItem"))
    except TimeoutError:
        return "import-menu-not-shown"
    app.click(item)
    title = s.PACK_IMPORT_FOLDER
    try:
        field = ui.wait(lambda: _field(app.window_nodes(title)))
    except TimeoutError:
        return "folder-dialog-not-opened"
    app.type_into(field, str(folder), enter=False)
    confirm = _by_id(app.window_nodes(title), CONFIRM_BUTTON)
    if confirm is None:
        return "select-folder-not-shown"
    app.press(confirm)
    try:
        ui.wait(lambda: app.window_nodes(title) is None)
    except TimeoutError:
        return "folder-dialog-not-closed"
    return None


def start_import(app: Any, pack_id: str, folder: Path) -> str | None:
    """Drive the import of ``folder`` for ``pack_id`` up to the closed dialogs; ``None`` once
    the import was started, else the reason it could not be (``PACK_FILE_MISSING`` first)."""
    if not has_pack_file(Path(os.fspath(folder))):
        return PACK_FILE_MISSING
    s, definition = ui.strings(), pack(pack_id)
    for step in (
        lambda: _open_details(app, s, definition.model),
        lambda: _accept_licence(app, s, definition),
        lambda: _choose_folder(app, s, definition.model, Path(os.fspath(folder))),
    ):
        reason = step()
        if reason is not None:
            return reason
    try:
        ui.wait(lambda: app.window_nodes(definition.model) is None)
    except TimeoutError:
        return "details-not-closed"
    return None


def wait_state(app: Any, pack_id: str, wanted: str, timeout_s: float | None = None) -> bool:
    """Whether the row of ``pack_id`` shows the state ``wanted`` within the timeout."""
    model = pack(pack_id).model
    try:
        ui.wait_nodes(app, lambda nodes: row_state(nodes, model) == wanted, timeout_s)
    except TimeoutError:
        return False
    return True


def import_folder(app: Any, pack_id: str, folder: Path) -> str:
    """Import ``folder`` and wait for *Validated* (300 s): "validated" or a named reason."""
    reason = start_import(app, pack_id, folder)
    if reason is not None:
        return reason
    validated = ui.strings().PACK_STATE_VALIDATED
    return (
        "validated" if wait_state(app, pack_id, validated, ui.MODEL_TIMEOUT_S) else "not-validated"
    )
