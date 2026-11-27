"""E-03: one Conversation session through the cable, stopped from Settings (contract §5).

VoR-02 path (spec §1.5): the N-01 WAV is checked against its SHA-256 in ``image.json``
before any app starts. Settings › Audio devices: "CABLE Output" is selected as Microphone
(compared with the cable's WASAPI name; only ``name_matches`` is stored); Conversation:
every voice switch ("Speak {language}") is off. Then **Start** (F8), wait for "Conversation running" (model
readiness, 300 s), play the WAV into "CABLE Input" with ``sounddevice`` and wait for a row
with an original and a translation in the *Transcript* list (``transcript_list.py``),
recorded once two consecutive reads agree. During the session every enabled workspace is visited: the strip shows "Conversation running" in each,
and in Call Bridge its Start is disabled with the help text "Stop the Conversation session
first". F9 is pressed in Settings; after the return to
Conversation the row texts (SHA-256 only, never the text), the list's scroll position,
the pair and the direction are unchanged; a scroll value that cannot be read fails. Two
masked screenshots (running, after); the *Transcript* list is masked in each.

The texts stay in memory: ``ctx.state["transcripts"]`` (the originals and the translations as
"{language}: {text}" lines, as the former panels showed them) for the E-10 export check and
``ctx.secrets`` (the rows, their parts and the lines without the language label) so the
artifact scan fails on any copy of them. The app stays open in ``ctx.state["app"]`` for E-10.
"""

from __future__ import annotations

from typing import Any

from native_e2e import audio, uia_app
from native_e2e.context import RunContext
from native_e2e.evidence.model import Check, Method, Row
from native_e2e.rows import ui
from native_e2e.rows.common import check, make_row
from native_e2e.rows.transcript_list import (  # noqa: F401 - re-exported for the other rows
    DIRECTION_LABEL,
    LIST,
    _scroll,
    digest,
    has_turn,
    items,
    panel,
    panels,
    remember,
    transcript,
    turn_parts,
    view,
)
from native_e2e.uia import Node

# Not in lianiq/ui/strings.py: the Call Bridge Start (ui/call_bridge_panel.py).
CALL_BRIDGE_START = "Start call bridge"
_remember = remember  # the former private name, used by E-15, E-19, E-40 and the voice rows


def _settled(app: Any, s: Any) -> dict[str, Any]:
    """The view once it shows a turn and two consecutive reads agree (``TimeoutError``)."""
    last: list[dict[str, Any]] = []

    def probe() -> dict[str, Any] | None:
        nodes = app.nodes()
        current = view(nodes, s)
        stable = bool(last) and last[-1] == current and has_turn(nodes, s)
        last[:] = [current]
        return current if stable else None

    return ui.wait(probe, ui.MODEL_TIMEOUT_S)


def _bridge_busy(nodes: list[Node], busy: str) -> bool:
    return any(
        node.visible
        and node.name == CALL_BRIDGE_START
        and not node.enabled
        and busy in node.description
        for node in nodes
    )


def _strip_gone(nodes: list[Node], s: Any, running: str) -> bool:
    return not ui.shows(nodes, running) and ui.find(nodes, s.SESSION_STRIP_NAME) is None


def _visit(app, s, checks: list[Check], running: str) -> bool:
    for entry in [e for e in ui.sidebar(app.nodes(), s.NAV_REGION) if e.enabled]:
        name = "strip-visible-" + entry.name.casefold().replace(" ", "-")
        if not ui.select(app, entry.name, s.NAV_REGION):
            checks.append(check(name, False, "not-selected"))
            return False
        if not ui.waited(checks, name, lambda: ui.shows(app.nodes(), running)):
            return False
        if entry.name == s.NAV_CALL_BRIDGE:
            busy = s.SESSION_BUSY.format(mode=s.NAV_CONVERSATION)
            probe = lambda busy=busy: _bridge_busy(app.nodes(), busy)
            if not ui.waited(checks, "call-bridge-start-disabled-busy", probe):
                return False
    return True


def _microphone(nodes: list[Node], s: Any) -> str | None:
    combo = ui.find(nodes, s.NOTICE_MICROPHONE, "ComboBox")
    return combo.value if combo is not None else None


def _cable_microphone(app, s, checks: list[Check]) -> bool:
    """Settings › Audio devices: select "CABLE Output" as Microphone (name never stored)."""
    expected = audio.wasapi_name(audio.CABLE_OUTPUT, "input")
    matches = False
    if expected is not None and ui.select(app, s.NAV_SETTINGS, s.NAV_REGION):
        combo = ui.find(app.nodes(), s.NOTICE_MICROPHONE, "ComboBox")
        try:
            if combo is not None:
                app.choose(combo, expected)
                ui.wait_nodes(app, lambda nodes: _microphone(nodes, s) == expected)
                matches = True
        except Exception:  # noqa: BLE001 - not selectable (UIA/pywinauto error) or timeout
            matches = False
    detail = f"name_matches: {str(matches).lower()}"
    checks.append(check("microphone-cable-selected", matches, detail))
    return matches


def _voice_switches(nodes, s) -> list[Node]:
    """The shown voice switches ("Speak {language}", one per pair language)."""
    prefix = s.VOICE_SWITCH_NAME.split("{", 1)[0]
    return [
        node
        for node in nodes
        if node.visible and node.control_type == "CheckBox" and node.name.startswith(prefix)
    ]


def _voice_output_off(app, s, checks: list[Check]) -> bool:
    """Conversation: turn every enabled voice switch off and wait until all read off."""
    name = "voice-output-off"
    if not ui.select(app, s.NAV_CONVERSATION, s.NAV_REGION):
        checks.append(check(name, False, "not-selected"))
        return False
    switches = _voice_switches(app.nodes(), s)
    if not switches:
        checks.append(check(name, False, "not-found"))
        return False
    for switch in switches:
        if switch.enabled and switch.selected is not False:
            app.press(switch)

    def off() -> bool:
        found = _voice_switches(app.nodes(), s)
        return bool(found) and all(node.selected is False for node in found)

    return ui.waited(checks, name, off)


def _session(ctx, app, path, checks: list[Check], artifacts: list) -> None:
    s = ui.strings()
    running = s.SESSION_RUNNING.format(mode=s.NAV_CONVERSATION)
    if not _cable_microphone(app, s, checks) or not _voice_output_off(app, s, checks):
        return
    app.keys("{F8}")
    probe = lambda: ui.shows(app.nodes(), running)
    if not ui.waited(checks, "session-running", probe, ui.MODEL_TIMEOUT_S):
        return
    audio.play_into_cable(path)
    try:
        before = _settled(app, s)
    except TimeoutError:
        checks.append(check("turn-in-original-and-translation", False, "timeout"))
        return
    checks.append(check("turn-in-original-and-translation", True))
    _remember(ctx, before["texts"])
    shot, artifact = ui.screenshot(ctx, app, "screens/e03-running.png", "screenshot-running-masked")
    checks.append(shot)
    artifacts.append(artifact)
    if not _visit(app, s, checks, running):
        return
    if not ui.select(app, s.NAV_SETTINGS, s.NAV_REGION):
        checks.append(check("stopped-with-f9-from-settings", False, "not-selected"))
        return
    app.keys("{F9}")
    probe = lambda: _strip_gone(app.nodes(), s, running)
    if not ui.waited(checks, "stopped-with-f9-from-settings", probe):
        return
    if not ui.select(app, s.NAV_CONVERSATION, s.NAV_REGION):
        checks.append(check("transcript-sha256-unchanged", False, "not-selected"))
        return
    after = view(app.nodes(), s)
    same = after["texts"] is not None and digest(after["texts"]) == digest(before["texts"])
    detail = f"sha256={digest(before['texts'])}" if same else "changed"
    readable = before["scroll"] is not None
    scroll = readable and after["scroll"] == before["scroll"]
    checks += [
        check("transcript-sha256-unchanged", same, detail),
        check("scroll-unchanged", scroll, None if readable else "unreadable"),
        check("pair-unchanged", before["pair"] is not None and after["pair"] == before["pair"]),
        check(
            "direction-unchanged",
            before["direction"] is not None and after["direction"] == before["direction"],
        ),
    ]
    shot, artifact = ui.screenshot(ctx, app, "screens/e03-after.png", "screenshot-after-masked")
    checks.append(shot)
    artifacts.append(artifact)


def run(ctx: RunContext) -> Row:
    try:
        path = audio.phrase_wav(ctx)
    except (OSError, ValueError, KeyError):
        checks = [check("test-phrase-sha256", False)]
        return make_row("E-03", checks, reason="test-phrase", method=Method.VIRTUAL_DEVICE)
    checks: list[Check] = [check("test-phrase-sha256", True)]
    artifacts: list = []
    app = uia_app.launch(ctx)
    ctx.state["app"] = app  # E-10 exports from this session; close_open closes it otherwise
    _session(ctx, app, path, checks, artifacts)
    return make_row(
        "E-03", checks, artifacts, reason="conversation-session", method=Method.VIRTUAL_DEVICE
    )
