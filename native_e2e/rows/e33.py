"""E-33: keyboard only on Language packs and the setup assistant (automated-po-rows spec §2.2).

The keyboard part of CAP-0171 E-10 (AC-26), read through UI Automation. On the image models
the row starts its own app and opens Language packs; once no pack row reads "Checking…" the
Tab cycle of the page is walked (every stop named). The detail of ``pack-actions-shown``
counts the stops the plan names that the image shows (**Update…**, **Download again**,
**Remove**, *Custom path* rows): they are walked only when shown.

**Run setup assistant** is focused, Space opens "Set up Lianiq", its first step's Tab cycle
is walked and Escape closes it (it stores ``first_run = "skipped"``: the settings are reset
at the end). The first pack row action that opens the details dialog (**Get…**,
**Update…**, **Download again**) is focused, Space opens the dialog (its title is the pack's
model), its Tab cycle is walked and Escape closes it: the licence box stays unticked, so
**Download** is never enabled and no connection is attempted. The first **Remove** is
focused, Space opens the confirmation "Remove", its Tab cycle is walked and Escape cancels
it; the pack rows are unchanged afterwards. A missing action is ``blocked`` with a named
reason (``no-details-action``, ``no-remove-action``), never a failure.
"""

from __future__ import annotations

from typing import Any

from native_e2e import packs_import, uia_app
from native_e2e.context import RunContext
from native_e2e.evidence.model import Check, Row, Status
from native_e2e.rows import keys, ui
from native_e2e.rows.common import check, make_row
from native_e2e.uia import Node


def _models() -> list[str]:
    return [definition.model for definition in packs_import.catalog().packs()]


def _row_names(nodes: list[Node], models: list[str]) -> list[str]:
    prefixes = tuple(f"{model}, " for model in models)
    return sorted(n.name for n in nodes if n.visible and n.name.startswith(prefixes))


def _ready(app: Any, s: Any, models: list[str]) -> bool:
    names = _row_names(app.nodes(), models)
    return bool(names) and not any(name.endswith(f", {s.PACK_STATE_CHECKING}") for name in names)


def _buttons(nodes: list[Node], labels: tuple[str, ...]) -> list[Node]:
    return [
        n
        for n in nodes
        if n.visible and n.enabled and n.control_type == "Button" and n.name in labels
    ]


def _shown(nodes: list[Node], s: Any) -> Check:
    counts = {
        "update": len(_buttons(nodes, (s.PACK_UPDATE,))),
        "redownload": len(_buttons(nodes, (s.PACK_REDOWNLOAD,))),
        "remove": len(_buttons(nodes, (s.PACK_REMOVE,))),
        "custom_path": sum(n.visible and s.PACK_CUSTOM_PATH in n.name for n in nodes),
    }
    return check("pack-actions-shown", True, " ".join(f"{k}={v}" for k, v in counts.items()))


def _assistant(app: Any, s: Any, checks: list[Check]) -> None:
    if keys.tab_to(app, keys.named(s.PACKS_RUN_ASSISTANT, "Button")) is None:
        checks.append(check("space-opens-assistant", False, "not-a-tab-stop"))
        return
    keys.dialog(app, checks, "assistant", "space", s.ASSIST_TITLE)


def _details(app: Any, s: Any, checks: list[Check], models: list[str]) -> None:
    labels = (s.PACK_GET, s.PACK_UPDATE, s.PACK_REDOWNLOAD)
    if not _buttons(app.nodes(), labels):
        checks.append(Check("no-details-action", Status.BLOCKED))
        return
    if keys.tab_to(app, lambda node: node.name in labels and node.control_type == "Button") is None:
        checks.append(check("space-opens-details", False, "not-a-tab-stop"))
        return
    title = lambda: next((m for m in models if app.window_nodes(m) is not None), None)
    keys.dialog(app, checks, "details", "space", title)


def _remove(app: Any, s: Any, checks: list[Check], models: list[str]) -> None:
    if not _buttons(app.nodes(), (s.PACK_REMOVE,)):
        checks.append(Check("no-remove-action", Status.BLOCKED))
        return
    if keys.tab_to(app, keys.named(s.PACK_REMOVE, "Button")) is None:
        checks.append(check("space-opens-remove", False, "not-a-tab-stop"))
        return
    before = _row_names(app.nodes(), models)
    if keys.dialog(app, checks, "remove", "space", s.PACK_REMOVE):
        same = _row_names(app.nodes(), models) == before
        checks.append(check("packs-unchanged-after-escape", same))


def _flow(app: Any, checks: list[Check]) -> None:
    s, models = ui.strings(), _models()
    if not ui.select(app, s.NAV_LANGUAGE_PACKS, s.NAV_REGION):
        checks.append(check("packs-tab-stops-named", False, "not-selected"))
        return
    ready = lambda: _ready(app, s, models)  # the first snapshot checks the pack files
    if not ui.waited(checks, "pack-states-shown", ready, ui.MODEL_TIMEOUT_S):
        return
    checks.append(keys.walk(app, "packs-tab-stops-named"))
    checks.append(_shown(app.nodes(), s))
    _assistant(app, s, checks)
    _details(app, s, checks, models)
    _remove(app, s, checks, models)


def run(ctx: RunContext) -> Row:
    checks: list[Check] = []
    uia_app.close_open(ctx)
    app = uia_app.launch(ctx)
    try:
        _flow(app, checks)
    finally:
        app.close()
        checks.append(check("settings-baseline-restored", uia_app.settings_reset(ctx)))
    failed = any(item.result is Status.FAIL for item in checks)
    blocked = next((item.name for item in checks if item.result is Status.BLOCKED), None)
    return make_row("E-33", checks, reason="keyboard" if failed else blocked or "keyboard")
