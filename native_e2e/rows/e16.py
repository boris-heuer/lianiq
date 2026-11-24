"""E-16: first launch with the setup assistant, offline (CAP-0171 e2e plan E-01, E-02, E-06).

Scratch models ``e16`` (empty) and no ``config/settings.local.json``: the app starts without
``--no-setup-assistant`` (``uia_app.launch(setup_assistant=True)`` deletes the file). The
assistant *Set up Lianiq* must open on *What do you want to do?*; before the first click the
app interpreter's non-loopback connection count since just before the launch must be 0
(``s04.count_since``). The four steps (usage, languages, audio check, readiness) are walked
with **Next** on their defaults (Conversation ticked, the pair preselected) and each is
screenshotted, masked (``provisioning.shot``: device lines, endpoint names, the models path).
**Skip** closes the assistant and stores ``provisioning.first_run = "skipped"``. The app is
closed and started again without the flag and with the stored settings: the assistant must
not open within ``NO_ASSISTANT_S``. ``settings_reset`` restores the S-03 baseline at the end,
also when the row fails; ``scratch_models`` restores the junction.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from native_e2e import models_swap, uia, uia_app
from native_e2e.evidence.model import Check, Row
from native_e2e.rows import provisioning, s04, ui
from native_e2e.rows.common import check, make_row

if TYPE_CHECKING:
    from native_e2e.context import RunContext
    from native_e2e.uia import Node

STEPS = (
    ("usage", "ASSIST_USAGE_TITLE"),
    ("languages", "ASSIST_LANG_TITLE"),
    ("audio", "ASSIST_AUDIO_TITLE"),
    ("readiness", "ASSIST_REVIEW_TITLE"),
)
NO_ASSISTANT_S = 8.0  # how long the relaunched window is watched for the assistant


def assistant(app: Any, s: Any) -> list[Node] | None:
    """The assistant's nodes: its own window, or its subtree in the main window's tree."""
    found = app.window_nodes(s.ASSIST_TITLE)
    if found is None:
        found = [node for node in app.nodes() if s.ASSIST_TITLE in node.parents] or None
    return found


def on_step(app: Any, s: Any, title: str) -> bool:
    nodes = assistant(app, s) or []
    return ui.find([n for n in nodes if n.control_type == "Text"], title) is not None


def first_run(ctx: RunContext) -> str | None:
    try:
        data = json.loads(ctx.local_settings.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    provisioning_block = data.get("provisioning") if isinstance(data, dict) else None
    return provisioning_block.get("first_run") if isinstance(provisioning_block, dict) else None


def relaunch(ctx: RunContext) -> uia_app.App:
    """Start the app without ``--no-setup-assistant`` and keep the settings file."""
    process = uia.launch_app(ctx.python, ctx.repo, setup_assistant=True)
    try:
        window = uia.connect(process)
    except Exception:
        uia.close_app(process)
        raise
    return uia_app.App(process, window)


def _press(app: Any, s: Any, label: str) -> bool:
    button = ui.find(assistant(app, s) or (), label, "Button")
    if button is None or not button.enabled:
        return False
    app.click(button)  # never focuses the main window under the modal dialog
    return True


def _walk(ctx: RunContext, app: Any, s: Any, checks: list[Check], artifacts: list) -> bool:
    for index, (slug, key) in enumerate(STEPS, 1):
        title = getattr(s, key)
        if index > 1:
            if not _press(app, s, s.ASSIST_NEXT):
                checks.append(check(f"step-{index}-{slug}-shown", False, "next-not-enabled"))
                return False
            if not ui.waited(
                checks, f"step-{index}-{slug}-shown", lambda t=title: on_step(app, s, t)
            ):
                return False
        relative = f"screens/e16-step{index}-{slug}.png"
        shot, artifact = provisioning.shot(
            ctx, app, relative, f"screenshot-step{index}-masked", lambda: assistant(app, s)
        )
        checks.append(shot)
        artifacts.append(artifact)
    if not _press(app, s, s.ASSIST_SKIP):
        checks.append(check("assistant-skipped", False, "skip-not-shown"))
        return False
    return ui.waited(checks, "assistant-skipped", lambda: assistant(app, s) is None)


def _first_launch(ctx: RunContext, s: Any, checks: list[Check], artifacts: list) -> bool:
    since = s04.now_iso()
    app = uia_app.launch(ctx, setup_assistant=True)
    try:
        probe = lambda: on_step(app, s, s.ASSIST_USAGE_TITLE)
        if not ui.waited(checks, "assistant-on-usage-step", probe):
            return False
        count = s04.count_since(ctx, since)
        checks.append(check("no-connection-before-first-click", count == 0, f"count={count}"))
        if not _walk(ctx, app, s, checks, artifacts):
            return False
    finally:
        app.close()
    skipped = first_run(ctx) == "skipped"
    checks.append(check("skip-stored", skipped, None if skipped else "not-skipped"))
    return skipped


def _second_launch(ctx: RunContext, s: Any, checks: list[Check], artifacts: list) -> None:
    app = relaunch(ctx)
    try:
        if not ui.waited(
            checks, "relaunch-window-shown", lambda: ui.sidebar(app.nodes(), s.NAV_REGION)
        ):
            return
        try:
            uia.wait_for(lambda: assistant(app, s) is not None, NO_ASSISTANT_S, ui.POLL_S)
            shown = True
        except TimeoutError:
            shown = False
        checks.append(check("relaunch-without-assistant", not shown))
        shot, artifact = provisioning.shot(
            ctx, app, "screens/e16-relaunch.png", "screenshot-relaunch-masked"
        )
        checks.append(shot)
        artifacts.append(artifact)
    finally:
        app.close()


def run(ctx: RunContext) -> Row:
    s = ui.strings()
    checks: list[Check] = []
    artifacts: list = []
    uia_app.close_open(ctx)  # the junction can only move while no app holds a model open
    try:
        with models_swap.scratch_models(ctx, "e16"):
            if _first_launch(ctx, s, checks, artifacts):
                _second_launch(ctx, s, checks, artifacts)
    finally:
        checks.append(check("settings-baseline-restored", uia_app.settings_reset(ctx)))
    return make_row("E-16", checks, artifacts, reason="first-launch")
