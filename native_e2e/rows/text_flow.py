"""Shared steps of the Text translation rows E-20..E-23 (CAP-0172 e2e plan E-01..E-08).

The plan's fixtures: D-03 (two German paragraphs, the E-13 text), D-04 (one Mandarin line),
D-05 (the sentinel) and D-06 (5,001 code points, ``over_limit``). ``type_source`` replaces
*Source text* by typing; ``translate`` presses **Translate** and returns both panes once the
result is current (no stale marker, **Translate** back) and two consecutive reads agree.
``shot`` writes a masked screenshot with *Source text* and *Translation* always masked;
``remember`` puts every fixture and result line into ``ctx.secrets``. Results are stored as
SHA-256 only. The clipboard helpers use ``win32clipboard`` (pywin32, in the native lock).
"""

from __future__ import annotations

from typing import Any

from native_e2e import audio, screens, uia
from native_e2e.context import RunContext
from native_e2e.evidence.model import Artifact, Check
from native_e2e.rows import ui
from native_e2e.rows.common import check
from native_e2e.rows.e03 import digest, panel
from native_e2e.rows.e13 import FIXTURE as D03
from native_e2e.rows.e13 import button, panes
from native_e2e.uia import Node

GERMAN, MANDARIN = "de", "zh-Hans"  # registry IDs; the visible names come from the registry
TRANSLATION_EDGES = {"mt-de-zh-hans": (GERMAN, MANDARIN), "mt-zh-hans-de": (MANDARIN, GERMAN)}
D04 = "早上好。这是一个测试。"
SENTINEL = "Lianiq sentinel QX7 Textprobe."
MIN_SECRET = 4
__all__ = ["D03", "D04", "SENTINEL", "button", "digest", "panel", "panes"]


def name(language: str) -> str:
    from lianiq.languages import BUILTIN_REGISTRY

    return BUILTIN_REGISTRY.display_name(language)


def limit() -> int:
    from lianiq.text_translation.limits import MAX_SOURCE_CODE_POINTS

    return int(MAX_SOURCE_CODE_POINTS)


def over_limit() -> str:
    """D-06: ``"Ab. "`` repeated, then ``"x"``: one code point above the limit (50,000)."""
    count = limit() + 1
    return ("Ab. " * (count // 4 + 1))[: count - 1] + "x"


def remember(ctx: RunContext, *texts: str | None) -> None:
    for text in [t for t in texts if t]:
        for line in [text.strip(), *(part.strip() for part in text.splitlines())]:
            if len(line) >= MIN_SECRET and line not in ctx.secrets:
                ctx.secrets.append(line)


def open_page(app: Any, s: Any, checks: list[Check], name_: str) -> bool:
    if ui.select(app, s.NAV_TEXT_TRANSLATION, s.NAV_REGION):
        return True
    checks.append(check(name_, False, "not-selected"))
    return False


def type_source(app: Any, s: Any, text: str) -> bool:
    """Replace *Source text* with ``text`` by typing (paragraphs with Enter)."""
    source = panel(app.nodes(), s.TEXT_SOURCE_LABEL)
    if source is None:
        return False
    app.press(source)
    lines = "{ENTER}".join(uia.escape_keys(line) for line in text.split("\n"))
    app.keys("^a{DELETE}" + lines)
    try:
        ui.wait(lambda: panes(app.nodes(), s)[0] == text)
    except TimeoutError:
        return False
    return True


def paste_source(app: Any, s: Any, text: str) -> bool:
    """Replace *Source text* with ``text`` through the clipboard (Ctrl+A, Ctrl+V)."""
    source = panel(app.nodes(), s.TEXT_SOURCE_LABEL)
    if source is None or not set_clipboard(text):
        return False
    app.press(source)
    app.keys("^a^v")
    try:
        ui.wait(lambda: panes(app.nodes(), s)[0] == text)
    except TimeoutError:
        return False
    return True


def combos(nodes: list[Node], s: Any) -> tuple[str | None, str | None]:
    found = [
        ui.find(nodes, label, "ComboBox")
        for label in (s.TEXT_SOURCE_LANGUAGE, s.TEXT_TARGET_LANGUAGE)
    ]
    return tuple(c.value if c is not None else None for c in found)  # type: ignore[return-value]


def direction(app: Any, s: Any, source: str, target: str) -> bool:
    """Make the page translate ``source`` → ``target`` (**Swap languages** when reversed)."""
    wanted = (name(source), name(target))
    if combos(app.nodes(), s) == wanted:
        return True
    swap = button(app.nodes(), s.TEXT_SWAP)
    if swap is None or combos(app.nodes(), s) != wanted[::-1]:
        return False
    app.press(swap)
    try:
        ui.wait(lambda: combos(app.nodes(), s) == wanted)
    except TimeoutError:
        return False
    return True


def stale(nodes: list[Node], s: Any) -> bool:
    return ui.shows(nodes, s.TEXT_STALE) or any(
        node.visible and s.TEXT_STALE in node.description for node in nodes
    )


def translate(app: Any, s: Any) -> tuple[str, str] | None:
    """**Translate**; both panes once the result is current and stable (300 s), else None."""
    pressed = button(app.nodes(), s.TEXT_TRANSLATE)
    if pressed is None:
        return None
    app.press(pressed)
    last: list[tuple] = []

    def probe() -> tuple[str, str] | None:
        nodes = app.nodes()
        current = panes(nodes, s)
        done = bool(current[1]) and button(nodes, s.TEXT_TRANSLATE) is not None
        done = done and not stale(nodes, s)
        steady = done and last == [current]
        last[:] = [current]
        return current if steady else None

    try:
        return ui.wait(probe, ui.MODEL_TIMEOUT_S)
    except TimeoutError:
        return None


def translated(ctx, app, s, checks: list[Check], name_: str) -> tuple[str, str] | None:
    """``translate`` recorded as the check ``name_`` (result SHA-256 only)."""
    result = translate(app, s)
    if result is None:
        checks.append(check(name_, False, "timeout"))
        return None
    remember(ctx, *result)
    checks.append(check(name_, True, f"sha256={digest([result[1]])}"))
    return result


def play_control(nodes: list[Node], s: Any) -> Node | None:
    """The play button whatever it reads (Play translation, Replay or Stop)."""
    labels = (s.TEXT_PLAY, s.TEXT_REPLAY, s.TEXT_STOP)
    return next(
        (n for n in nodes if n.visible and n.control_type == "Button" and n.name in labels), None
    )


def running(nodes: list[Node], s: Any) -> bool:
    return ui.shows(nodes, s.SESSION_RUNNING.format(mode=s.NAV_TEXT_TRANSLATION))


def idle(nodes: list[Node], s: Any) -> bool:
    gone = not running(nodes, s) and ui.find(nodes, s.SESSION_STRIP_NAME) is None
    return gone and ui.find(nodes, s.TEXT_REPLAY, "Button") is not None


def strip_gone(nodes: list[Node], s: Any) -> bool:
    return ui.find(nodes, s.SESSION_STRIP_NAME) is None


def shot(ctx: RunContext, app: Any, relative: str, texts, name_: str) -> tuple[Check, Artifact]:
    """A masked screenshot: both panes always, endpoint names, device combos, text needles."""
    s = ui.strings()
    fields = (s.TEXT_SOURCE_LABEL, s.TEXT_RESULT_LABEL)
    names = [*audio.endpoint_names(), *ui.transcript_needles([t for t in texts if t])]
    combos_ = (s.NOTICE_MICROPHONE, s.NOTICE_SPEAKERS)
    artifact, masked = screens.capture(ctx, app, relative, names, combos_, fields)
    return check(name_, True, f"masked={masked}"), artifact


def clipboard_text() -> str | None:
    try:
        import win32clipboard
        import win32con

        win32clipboard.OpenClipboard()
        try:
            return str(win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT))
        finally:
            win32clipboard.CloseClipboard()
    except Exception:  # noqa: BLE001 - no text on the clipboard, or it is held elsewhere
        return None


def set_clipboard(text: str) -> bool:
    try:
        import win32clipboard
        import win32con

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        finally:
            win32clipboard.CloseClipboard()
    except Exception:  # noqa: BLE001 - held by another process: the row records the failure
        return False
    return True


# The setup assistant (E-20)


def label(kind: str, subject: str | None = None) -> str:
    """The readiness row's leading text of a requirement (``describe``, capitalised)."""
    from lianiq.languages import BUILTIN_REGISTRY, DirectedEdge
    from lianiq.languages.requirements import Requirement, RequirementKind, describe

    if kind == "translation" and subject is not None:
        subject = DirectedEdge(*TRANSLATION_EDGES[subject]).key  # subject: the pack id
    text = describe(Requirement(RequirementKind(kind), subject), BUILTIN_REGISTRY)
    return text[:1].upper() + text[1:]


def assistant(app: Any, s: Any) -> list[Node]:
    return app.window_nodes(s.ASSIST_TITLE) or []


def review_rows(nodes: list[Node], s: Any) -> list[str]:
    sep = " — "
    titles = (s.ASSIST_REVIEW_TITLE, s.PACK_STATE_CHECKING)
    return [
        n.name
        for n in nodes
        if n.visible
        and n.control_type == "Text"
        and n.name.count(sep) >= 2
        and n.name not in titles
    ]
