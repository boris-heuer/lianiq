"""Shared steps of the offline-provisioning rows E-16..E-19 (CAP-0171; spec §2.2).

``filled`` matches a shown text against a ``strings`` template whose one field is unknown in
advance (the host of "Download unavailable: no connection to {host}. …", the file of an
integrity failure). ``shot`` writes a masked screenshot of the window and, when given, of the
setup assistant over it: besides the endpoint names, the device combos and the transcript
needles of ``ui.screenshot`` it masks the *Models folder* line of Language packs (a path
under the user's profile) and every "role: device" line of the assistant's audio check.
``remove`` presses a pack row's **Remove** and answers the confirmation with **Yes**.
``catalog_ids`` lists every catalog pack (Language packs shows each one); ``pair_ids`` only
the German–Mandarin packs the rows import (the rule of ``e30.packs`` with both voices), so
packs of other pairs (english-mandarin-pair) need no image folder or pack file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from native_e2e import audio, packs_import, screens
from native_e2e.rows import ui
from native_e2e.rows.common import check
from native_e2e.rows.voice import GERMAN, MANDARIN

if TYPE_CHECKING:
    from collections.abc import Callable

    from native_e2e.context import RunContext
    from native_e2e.evidence.model import Artifact, Check
    from native_e2e.uia import Node

# The QMessageBox.question button of ``language_packs_layout.confirm_remove``: a Qt stock
# text, not in lianiq/ui/strings.py.
YES = "Yes"


def catalog_ids() -> tuple[str, ...]:
    return tuple(definition.id for definition in packs_import.catalog().packs())


def pair_ids() -> tuple[str, ...]:
    """Every German–Mandarin pack: recognition for both, both edges, both voices."""
    from lianiq.packs.catalog import PackKind

    pair = {GERMAN, MANDARIN, f"{GERMAN}>{MANDARIN}", f"{MANDARIN}>{GERMAN}"}

    def keep(p) -> bool:
        if p.kind is PackKind.RECOGNITION:
            return {GERMAN, MANDARIN} <= set(p.provides)
        return set(p.provides) <= pair

    return tuple(p.id for p in packs_import.catalog().packs() if keep(p))


def filled(nodes: list[Node], template: str, field: str) -> bool:
    """Whether a shown element's name is ``template`` with any text in ``{field}``."""
    head, _, tail = template.partition("{" + field + "}")
    return any(
        node.visible
        and node.name.startswith(head)
        and node.name.endswith(tail)
        and len(node.name) > len(head) + len(tail)
        for node in nodes
    )


def states(nodes: list[Node], models: list[str]) -> list[str | None]:
    return [packs_import.row_state(nodes, model) for model in models]


def _names(ctx: RunContext) -> list[str]:
    s = ui.strings()
    folder = s.PACKS_FOLDER.split("{path}")[0]  # "Models folder: " — the line shows a path
    needles = ui.transcript_needles(ctx.state.get("transcripts", []))
    return [*audio.endpoint_names(), folder, *needles]


def _union(rect, nodes: list[Node]) -> tuple[int, int, int, int]:
    left, top, right, bottom = rect
    for node in nodes:
        x0, y0, x1, y1 = node.rect
        if node.visible and x1 > x0 and y1 > y0:
            left, top, right, bottom = min(left, x0), min(top, y0), max(right, x1), max(bottom, y1)
    return left, top, right, bottom


def shot(
    ctx: RunContext,
    app: Any,
    relative: str,
    name: str,
    dialog: Callable[[], list[Node] | None] | None = None,
) -> tuple[Check, Artifact]:
    s = ui.strings()
    names = _names(ctx)
    combos = (s.NOTICE_MICROPHONE, s.NOTICE_SPEAKERS)

    def rects() -> list:
        extra = (dialog() if dialog else None) or []
        found = screens.mask_rects([*app.nodes(), *extra], names, combos)
        lines = [n.rect for n in extra if n.visible and n.control_type == "Text" and ": " in n.name]
        return found + lines

    before = rects()
    window = _union(app.rect, (dialog() if dialog else None) or [])
    png = screens.grab(window)
    found = list(dict.fromkeys(before + rects()))
    artifact = screens.write_masked(ctx, relative, png, window[:2], found)
    return check(name, True, f"masked={len(found)}"), artifact


def remove(app: Any, model: str, checks: list[Check], name: str) -> bool:
    """**Remove** on the row of ``model``, then **Yes** in the confirmation."""
    s = ui.strings()
    button = packs_import._row_button(app.nodes(), model, (s.PACK_REMOVE,))
    if button is None:
        checks.append(check(name, False, "remove-not-shown"))
        return False
    app.press(button)
    try:
        yes = ui.wait(lambda: ui.find(app.window_nodes(s.PACK_REMOVE) or (), YES, "Button"))
    except TimeoutError:
        checks.append(check(name, False, "confirmation-not-shown"))
        return False
    app.click(yes)
    return True
