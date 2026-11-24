"""E-21 and E-22 on the E-20 scratch models and app (CAP-0172 e2e plan E-02..E-04).

E-21 (plan E-02, no voice installed): the D-03 result of E-20 is current; **Play translation**
is disabled with "Play translation needs the Mandarin (Simplified) voice." and **Open Language
packs**; **Swap languages**; D-04 typed and translated; Play then names the German voice.

E-22 (plan E-03, E-04): both voices imported (``packs_import.import_folder``); Settings ›
Audio devices: "CABLE Input" as Speakers (``name_matches`` only); German → Mandarin
(Simplified), D-03, **Translate**; **Copy translation**: the clipboard's SHA-256 equals the
result's; **Play translation** ("Text translation running"), **Stop**: the button reads
**Replay**; **Replay** plays again until it ends. One character added to the source shows the
stale marker at once with **Copy translation** and **Replay** disabled; a changed target keeps
them disabled. Results, clipboard and texts are stored as SHA-256 only, both panes masked.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from native_e2e import packs_import
from native_e2e.context import RunContext
from native_e2e.evidence.model import Check
from native_e2e.rows import e13, text_flow, ui
from native_e2e.rows.common import check
from native_e2e.rows.text_flow import GERMAN, MANDARIN, button, digest, name
from native_e2e.uia import Node

SCREENS = ("screens/e21-no-voice.png", "screens/e22-playing.png", "screens/e22-stale.png")
VOICE_PACKS = ("tts-de-thorsten-medium", "tts-zh-hans-aishell3")
STALE_S = 2.0  # "at once": the marker and the disabled controls within one short poll


def _no_voice(nodes: list[Node], s: Any, language: str) -> bool:
    play = ui.find(nodes, s.TEXT_PLAY, "Button")
    hint = ui.shows(nodes, s.TEXT_VOICE_MISSING.format(language=name(language)))
    return play is not None and not play.enabled and hint and ui.shows(nodes, s.PACKS_OPEN)


def e21(ctx: RunContext, app: Any, artifacts: list) -> list[Check]:
    s, checks = ui.strings(), []
    if not text_flow.open_page(app, s, checks, "translation-german-mandarin"):
        return checks
    nodes = app.nodes()
    first = text_flow.panes(nodes, s)
    current = bool(first[1]) and not text_flow.stale(nodes, s)
    checks.append(
        check("translation-german-mandarin", current, f"sha256={digest([first[1] or ''])}")
    )
    probe = lambda: _no_voice(app.nodes(), s, MANDARIN)
    if not ui.waited(checks, "play-unavailable-mandarin-voice", probe):
        return checks
    if not text_flow.direction(app, s, MANDARIN, GERMAN):
        return [*checks, check("swapped", False)]
    checks.append(check("swapped", True))
    if not text_flow.type_source(app, s, text_flow.D04):
        return [*checks, check("translation-mandarin-german", False, "not-typed")]
    text_flow.remember(ctx, text_flow.D04)
    result = text_flow.translated(ctx, app, s, checks, "translation-mandarin-german")
    if result is None:
        return checks
    probe = lambda: _no_voice(app.nodes(), s, GERMAN)
    ui.waited(checks, "play-unavailable-german-voice", probe)
    shot, artifact = text_flow.shot(ctx, app, SCREENS[0], result, "screenshot-no-voice-masked")
    artifacts.append(artifact)
    return [*checks, shot]


def _voices(app: Any, folders: dict[str, Path], checks: list[Check]) -> bool:
    for pack_id in VOICE_PACKS:
        outcome = packs_import.import_folder(app, pack_id, folders[pack_id])
        checks.append(check(f"imported-{pack_id}", outcome == "validated", outcome))
        if outcome != "validated":
            return False
    return True


def _copied(app: Any, s: Any, result: str, checks: list[Check]) -> None:
    copy = button(app.nodes(), s.TEXT_COPY_TRANSLATION)
    if copy is None:
        checks.append(check("clipboard-equals-result", False, "copy-disabled"))
        return
    app.press(copy)
    expected = digest([result])
    try:
        ui.wait(
            lambda: (
                (text := text_flow.clipboard_text()) is not None
                and digest([text.replace("\r\n", "\n")]) == expected
            )
        )
    except TimeoutError:
        checks.append(check("clipboard-equals-result", False, "differs"))
        return
    checks.append(check("clipboard-equals-result", True, f"sha256={expected}"))


def _played(ctx, app: Any, s: Any, result, checks: list[Check], artifacts: list) -> bool:
    play = button(app.nodes(), s.TEXT_PLAY)
    if play is None:
        checks.append(check("strip-text-translation-running", False, "play-disabled"))
        return False
    app.press(play)
    probe = lambda: text_flow.running(app.nodes(), s)
    if not ui.waited(checks, "strip-text-translation-running", probe, ui.MODEL_TIMEOUT_S):
        return False
    shot, artifact = text_flow.shot(ctx, app, SCREENS[1], result, "screenshot-playing-masked")
    checks.append(shot)
    artifacts.append(artifact)
    stop = button(app.nodes(), s.TEXT_STOP)
    if stop is None:
        checks.append(check("stopped-reads-replay", False, "stop-not-shown"))
        return False
    app.press(stop)
    if not ui.waited(checks, "stopped-reads-replay", lambda: text_flow.idle(app.nodes(), s)):
        return False
    replay = button(app.nodes(), s.TEXT_REPLAY)
    if replay is None:
        checks.append(check("replay-played", False, "replay-disabled"))
        return False
    app.press(replay)
    try:
        ui.wait(lambda: text_flow.running(app.nodes(), s), ui.MODEL_TIMEOUT_S)
        ui.wait(lambda: text_flow.idle(app.nodes(), s), ui.MODEL_TIMEOUT_S)
    except TimeoutError:
        checks.append(check("replay-played", False, "timeout"))
        return False
    checks.append(check("replay-played", True))
    return True


def _locked(nodes: list[Node], s: Any) -> bool:
    """Stale marker shown; Copy translation and the play button disabled."""
    copy = ui.find(nodes, s.TEXT_COPY_TRANSLATION, "Button")
    play = text_flow.play_control(nodes, s)
    off = copy is not None and not copy.enabled and play is not None and not play.enabled
    return text_flow.stale(nodes, s) and off


def _stale(ctx, app: Any, s: Any, result, checks: list[Check], artifacts: list) -> None:
    source = text_flow.panel(app.nodes(), s.TEXT_SOURCE_LABEL)
    if source is None:
        checks.append(check("stale-at-once-controls-disabled", False, "not-found"))
        return
    app.press(source)
    app.keys("^{END}x")
    probe = lambda: _locked(app.nodes(), s)
    if not ui.waited(checks, "stale-at-once-controls-disabled", probe, STALE_S):
        return
    shot, artifact = text_flow.shot(ctx, app, SCREENS[2], result, "screenshot-stale-masked")
    checks.append(shot)
    artifacts.append(artifact)
    target = ui.find(app.nodes(), s.TEXT_TARGET_LANGUAGE, "ComboBox")
    try:
        if target is None:
            raise TimeoutError
        app.choose(target, name(GERMAN))  # the source language: the page swaps the pair
        ui.wait(lambda: text_flow.combos(app.nodes(), s) == (name(MANDARIN), name(GERMAN)))
    except Exception:  # noqa: BLE001 - not selectable (UIA error) or not applied in time
        checks.append(check("target-changed-still-disabled", False, "not-changed"))
        return
    probe = lambda: _locked(app.nodes(), s)
    ui.waited(checks, "target-changed-still-disabled", probe, STALE_S)


def e22(ctx: RunContext, app: Any, folders: dict[str, Path], artifacts: list) -> list[Check]:
    s, checks = ui.strings(), []
    if not _voices(app, folders, checks) or not e13._cable_speakers(app, s, checks):
        return checks
    if not text_flow.open_page(app, s, checks, "translation-shown"):
        return checks
    if not text_flow.direction(app, s, GERMAN, MANDARIN):
        return [*checks, check("translation-shown", False, "direction")]
    if not text_flow.type_source(app, s, text_flow.D03):
        return [*checks, check("translation-shown", False, "not-typed")]
    result = text_flow.translated(ctx, app, s, checks, "translation-shown")
    if result is None:
        return checks
    _copied(app, s, result[1], checks)
    if _played(ctx, app, s, result, checks, artifacts):
        _stale(ctx, app, s, result, checks, artifacts)
    return checks
