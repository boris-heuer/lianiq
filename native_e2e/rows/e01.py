"""E-01: the shell at launch in the real window (contract §5; CAP-0168 E-01, AC-03).

Launch ``python -m lianiq`` (``QT_QPA_PLATFORM`` unset) and read the sidebar with pywinauto
``backend="uia"``: seven entries in order (CAP-0177 adds Meeting second, enabled),
Conversation selected, the planned entries disabled with the description "Planned — not
available yet", Call Bridge marked "Experimental". The
shown Conversation page has no Call Bridge control, Model profile, CUDA box or hardware
subtitle (controls of hidden pages and the sidebar's own entries do not count). Before Start
no app process has a file under the models folder open or mapped (psutil ``open_files()``
and ``memory_maps()``; only the counts are stored); no process inspected is a failure. One
masked screenshot.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from native_e2e import uia_app
from native_e2e.context import RunContext
from native_e2e.evidence.model import Check, Row
from native_e2e.rows import ui
from native_e2e.rows.common import check, make_row

SCREEN = "screens/e01-conversation.png"
# The CAP-0168 texts that left the Conversation page; the last three are not in strings.py
# any more (the CUDA box and the hardware subtitle were removed, spec §2.3.3 of CAP-0168).
REMOVED_LITERALS = ("CUDA", "Ryzen", "Local · Private")


def _normal(path: str) -> str:
    text = str(path).replace("/", "\\")
    text = text.removeprefix("\\\\?\\")
    return text.rstrip("\\").casefold()


def models_in_use(processes: Iterable[Any], roots: Iterable[str]) -> int:
    """How many open or mapped files of the processes lie under one of ``roots``."""
    prefixes = [_normal(root) + "\\" for root in roots if root]
    count = 0
    for process in processes:
        for item in [*process.open_files(), *process.memory_maps()]:
            if any(_normal(item.path).startswith(prefix) for prefix in prefixes):
                count += 1
    return count


def _model_roots(ctx: RunContext) -> list[str]:
    roots = [str(ctx.repo / "models")]
    try:
        roots.append(str(ctx.image().get("models_dir") or ""))
    except (OSError, ValueError):
        pass  # no image.json: the checkout's models folder still counts
    roots += [str(Path(root).resolve()) for root in roots if root]
    return roots


def _sidebar_checks(entries, s) -> list[Check]:
    expected = [
        s.NAV_CONVERSATION,
        s.NAV_MEETING,
        s.NAV_TEXT_TRANSLATION,
        s.NAV_LISTEN,
        s.NAV_CALL_BRIDGE,
        s.NAV_LANGUAGE_PACKS,
        s.NAV_SETTINGS,
    ]
    planned = (s.NAV_LISTEN,)  # CAP-0172 enabled Text translation, CAP-0171 Language packs
    names = [entry.name for entry in entries]
    tops = [entry.rect[1] for entry in entries]
    by = {entry.name: entry for entry in entries}
    conversation = by.get(s.NAV_CONVERSATION)
    others_selected = [entry for entry in entries if entry.selected and entry is not conversation]
    planned_ok = all(
        name in by and not by[name].enabled and by[name].description == s.NAV_PLANNED_DESCRIPTION
        for name in planned
    )
    enabled_ok = all(name in by and by[name].enabled for name in expected if name not in planned)
    bridge = by.get(s.NAV_CALL_BRIDGE)
    return [
        check(
            "sidebar-seven-entries-in-order",
            names == expected and tops == sorted(tops),
            f"{len(names)} entries",
        ),
        check(
            "conversation-selected",
            conversation is not None and conversation.selected is True and not others_selected,
        ),
        check("planned-entries-disabled-with-description", planned_ok and enabled_ok),
        check(
            "call-bridge-experimental",
            bridge is not None and s.NAV_EXPERIMENTAL in (bridge.description or ""),
        ),
    ]


def _removed_shown(nodes, s) -> list[str]:
    terms = (s.NAV_CALL_BRIDGE, s.DIAG_MODEL_PROFILE, s.DIAG_MODEL_PROFILE_BALANCED)
    terms += REMOVED_LITERALS
    found: set[str] = set()
    for node in nodes:
        if not node.visible or s.NAV_REGION in node.parents or node.name == s.NAV_REGION:
            continue
        text = " ".join(node.texts()).casefold()
        found.update(term for term in terms if term.casefold() in text)
    return sorted(found)


def _checks(ctx: RunContext, app: Any) -> tuple[list[Check], list]:
    s = ui.strings()
    try:
        ui.wait_nodes(app, lambda nodes: len(ui.sidebar(nodes, s.NAV_REGION)) >= 7)
    except TimeoutError:
        pass  # the order check below records what is shown
    nodes = app.nodes()
    checks = _sidebar_checks(ui.sidebar(nodes, s.NAV_REGION), s)
    removed = _removed_shown(nodes, s)
    checks.append(
        check("conversation-without-removed-controls", not removed, ", ".join(removed) or None)
    )
    try:
        processes = list(app.processes())
        count = models_in_use(processes, _model_roots(ctx))
        detail = f"{count} file(s) in {len(processes)} process(es)"
        passed = count == 0 and bool(processes)
        checks.append(check("no-model-file-open-before-start", passed, detail))
    except Exception as error:  # noqa: BLE001 - unreadable process: not proven
        checks.append(check("no-model-file-open-before-start", False, type(error).__name__))
    shot, artifact = ui.screenshot(ctx, app, SCREEN, "screenshot-masked")
    checks.append(shot)
    return checks, [artifact]


def run(ctx: RunContext) -> Row:
    app = uia_app.launch(ctx)
    try:
        checks, artifacts = _checks(ctx, app)
    finally:
        app.close()
    return make_row("E-01", checks, artifacts, reason="shell-at-launch")
