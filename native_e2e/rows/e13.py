"""E-13: Text translation played on the virtual cable (CAP-0172 AC-37; its e2e plan row E-09).

Settings › Audio devices: "CABLE Input" is selected as Speakers (compared with the cable's
WASAPI name; only ``name_matches`` is stored). Sidebar **Text translation**; the plan's German
fixture text D-03 (two paragraphs) is typed into *Source text*; **Translate**; the result in
*Translation* is recorded once two consecutive reads agree (model readiness, 300 s) as its
SHA-256, never the text. **Play translation** plays it on the cable: the strip shows "Text
translation running"; F9 stops it, the strip goes away and the button reads **Replay** (idle);
both texts are unchanged. Two screenshots (result, playing) mask both panes whatever they
show. The fixture and the result lines go to ``ctx.secrets``, so the redaction scan fails on
any stored copy of them. The row runs inside the S-04 offline window and closes the app.
"""

from __future__ import annotations

from typing import Any

from native_e2e import audio, screens, uia, uia_app
from native_e2e.context import RunContext
from native_e2e.evidence.model import Artifact, Check, Method, Row
from native_e2e.rows import ui
from native_e2e.rows.common import check, make_row
from native_e2e.rows.e03 import digest, panel
from native_e2e.uia import Node

PARAGRAPHS = (  # e2e plan D-03
    "Guten Morgen. Heute testen wir die Textübersetzung.",
    "Der zweite Absatz hat zwei Sätze. Er endet hier.",
)
FIXTURE = "\n\n".join(PARAGRAPHS)
SCREENS = ("screens/e13-result.png", "screens/e13-playing.png")
MIN_SECRET = 4


def text_of(node: Node | None) -> str | None:
    if node is None or node.value is None:
        return None
    return node.value.replace("\r\n", "\n").replace("\r", "\n")


def panes(nodes: list[Node], s: Any) -> tuple[str | None, str | None]:
    return (
        text_of(panel(nodes, s.TEXT_SOURCE_LABEL)),
        text_of(panel(nodes, s.TEXT_RESULT_LABEL)),
    )


def button(nodes: list[Node], name: str) -> Node | None:
    found = ui.find(nodes, name, "Button")
    return found if found is not None and found.enabled else None


def _settled(app: Any, s: Any) -> tuple[str, str]:
    """Both panes once the result shows, Translate is back and two reads agree."""
    last: list[tuple] = []

    def probe() -> tuple[str, str] | None:
        nodes = app.nodes()
        current = panes(nodes, s)
        done = bool(current[1]) and button(nodes, s.TEXT_TRANSLATE) is not None
        stable = done and last == [current]
        last[:] = [current]
        return current if stable else None

    return ui.wait(probe, ui.MODEL_TIMEOUT_S)


def _remember(ctx: RunContext, texts: tuple[str, ...]) -> None:
    for line in [line.strip() for text in texts for line in text.splitlines()]:
        if len(line) >= MIN_SECRET and line not in ctx.secrets:
            ctx.secrets.append(line)


def _shot(ctx: RunContext, app: Any, index: int, texts) -> tuple[Check, Artifact]:
    s = ui.strings()
    fields = (s.TEXT_SOURCE_LABEL, s.TEXT_RESULT_LABEL)
    shown = all(panel(app.nodes(), name) is not None for name in fields)
    names = [*audio.endpoint_names(), *ui.transcript_needles(texts)]
    combos = (s.NOTICE_MICROPHONE, s.NOTICE_SPEAKERS)
    artifact, masked = screens.capture(ctx, app, SCREENS[index], names, combos, fields)
    detail = f"masked={masked}" if shown else "pane-missing"
    return check(f"screenshot-{('result', 'playing')[index]}-masked", shown, detail), artifact


def _speakers(nodes: list[Node], s: Any) -> str | None:
    combo = ui.find(nodes, s.NOTICE_SPEAKERS, "ComboBox")
    return combo.value if combo is not None else None


def _cable_speakers(app: Any, s: Any, checks: list[Check]) -> bool:
    """Settings › Audio devices: select "CABLE Input" as Speakers (name never stored)."""
    expected = audio.wasapi_name(audio.CABLE_INPUT, "output")
    matches = False
    if expected is not None and ui.select(app, s.NAV_SETTINGS, s.NAV_REGION):
        combo = ui.find(app.nodes(), s.NOTICE_SPEAKERS, "ComboBox")
        try:
            if combo is not None:
                app.choose(combo, expected)
                ui.wait_nodes(app, lambda nodes: _speakers(nodes, s) == expected)
                matches = True
        except Exception:  # noqa: BLE001 - not selectable (UIA/pywinauto error) or timeout
            matches = False
    checks.append(
        check("speakers-cable-selected", matches, f"name_matches: {str(matches).lower()}")
    )
    return matches


def _typed(app: Any, s: Any, checks: list[Check]) -> bool:
    if not ui.select(app, s.NAV_TEXT_TRANSLATION, s.NAV_REGION):
        checks.append(check("fixture-typed", False, "not-selected"))
        return False
    source = panel(app.nodes(), s.TEXT_SOURCE_LABEL)
    if source is None:
        checks.append(check("fixture-typed", False, "not-found"))
        return False
    app.press(source)
    first, second = (uia.escape_keys(text) for text in PARAGRAPHS)
    app.keys(f"^a{{DELETE}}{first}{{ENTER}}{{ENTER}}{second}")
    probe = lambda: panes(app.nodes(), s)[0] == FIXTURE
    return ui.waited(checks, "fixture-typed", probe)


def _flow(ctx: RunContext, app: Any, checks: list[Check], artifacts: list) -> None:
    s = ui.strings()
    running = s.SESSION_RUNNING.format(mode=s.NAV_TEXT_TRANSLATION)
    if not _cable_speakers(app, s, checks) or not _typed(app, s, checks):
        return
    translate = button(app.nodes(), s.TEXT_TRANSLATE)
    if translate is None:
        checks.append(check("translation-shown", False, "translate-disabled"))
        return
    app.press(translate)
    try:
        before = _settled(app, s)
    except TimeoutError:
        checks.append(check("translation-shown", False, "timeout"))
        return
    _remember(ctx, before)
    checks.append(check("translation-shown", True, f"sha256={digest([before[1]])}"))
    shot, artifact = _shot(ctx, app, 0, before)
    checks.append(shot)
    artifacts.append(artifact)
    play = button(app.nodes(), s.TEXT_PLAY)
    if play is None:
        checks.append(check("strip-text-translation-running", False, "play-disabled"))
        return
    app.press(play)
    probe = lambda: ui.shows(app.nodes(), running)
    if not ui.waited(checks, "strip-text-translation-running", probe, ui.MODEL_TIMEOUT_S):
        return
    shot, artifact = _shot(ctx, app, 1, before)
    checks.append(shot)
    artifacts.append(artifact)
    app.keys("{F9}")

    def idle() -> bool:
        nodes = app.nodes()
        gone = not ui.shows(nodes, running) and ui.find(nodes, s.SESSION_STRIP_NAME) is None
        return gone and ui.find(nodes, s.TEXT_REPLAY, "Button") is not None

    if ui.waited(checks, "stopped-with-f9-idle", idle):
        same = panes(app.nodes(), s) == before
        checks.append(check("texts-unchanged", same, None if same else "changed"))


def run(ctx: RunContext) -> Row:
    checks: list[Check] = []
    artifacts: list[Artifact] = []
    app = uia_app.launch(ctx)
    try:
        _flow(ctx, app, checks, artifacts)
    finally:
        app.close()
    return make_row(
        "E-13", checks, artifacts, reason="text-translation", method=Method.VIRTUAL_DEVICE
    )
