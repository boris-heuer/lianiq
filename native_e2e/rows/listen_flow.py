"""Shared steps of the Listen & translate rows E-24..E-26 (CAP-0170 e2e plan E-01..E-04, E-06,
E-08; spec §2.2).

``packs`` follows the E-30 rule: only packs of the German–Mandarin pair (the recognition pack
covering both, both translation edges; no voice), so packs of other pairs, such as
english-mandarin-pair, never need a folder. The setup assistant steps (usage, languages,
readiness rows "<item> — <status> — <tail>", **Get…** › pack dialog › licence › **Import…** ›
**Choose folder…** through ``packs_import``) read every text from ``lianiq.ui.strings``.
*Transcript* rows are read as "<time>, <source>: <text>. <target>: <outcome>"; ``settle``
returns the rows added after ``count`` once none is in progress and the list has not changed
for ``SETTLE_S``. Texts go to ``ctx.secrets`` (``remember``); rows store counts and SHA-256.
"""

from __future__ import annotations

import difflib
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from native_e2e import audio, packs_import, screens
from native_e2e.evidence.model import Artifact, Check
from native_e2e.rows import e14, ui
from native_e2e.rows.common import check
from native_e2e.uia import Node

GERMAN, MANDARIN = "de", "zh-Hans"  # registry IDs of the image pair
USAGE = "listen-and-translate"  # lianiq.packs.usage profile id
SETTLE_S = 5.0  # the transcript must stay unchanged this long
MIN_SECRET = 4
SEP = " — "


def name(language: str) -> str:
    from lianiq.languages import BUILTIN_REGISTRY
    from lianiq.languages.registry import LanguageId

    return BUILTIN_REGISTRY.display_name(LanguageId(language))


def packs() -> dict[str, str]:
    """Role → pack id: "recognition" (both languages) and the edges "de>zh-Hans",
    "zh-Hans>de"; packs of other pairs and voices are left out."""
    from lianiq.packs.catalog import PackKind

    found: dict[str, str] = {}
    edges = {f"{GERMAN}>{MANDARIN}", f"{MANDARIN}>{GERMAN}"}
    for p in packs_import.catalog().packs():
        if p.kind is PackKind.RECOGNITION and {GERMAN, MANDARIN} <= set(p.provides):
            found.setdefault("recognition", p.id)
        elif p.kind is PackKind.TRANSLATION and len(p.provides) == 1 and p.provides[0] in edges:
            found[p.provides[0]] = p.id
    return found


def describe(kind: str, subject: str | None = None) -> str:
    from lianiq.languages import BUILTIN_REGISTRY
    from lianiq.languages.requirements import Requirement, RequirementKind
    from lianiq.languages.requirements import describe as text

    return text(Requirement(RequirementKind(kind), subject), BUILTIN_REGISTRY)


def label(kind: str, subject: str | None = None) -> str:
    """A readiness row's leading text (``describe``, capitalised)."""
    text = describe(kind, subject)
    return text[:1].upper() + text[1:]


def missing(s: Any, source: str, target: str) -> str:
    """The Listen readiness text naming only the missing translation ``source → target``."""
    return s.MODE_UNAVAILABLE.format(items=describe("translation", f"{source}>{target}"))


# Setup assistant -----------------------------------------------------------------------


def assistant(app: Any, s: Any) -> list[Node]:
    return app.window_nodes(s.ASSIST_TITLE) or []


def review_rows(nodes: list[Node], s: Any) -> list[str]:
    titles = (s.ASSIST_REVIEW_TITLE, s.PACK_STATE_CHECKING)
    return [
        n.name
        for n in nodes
        if n.visible
        and n.control_type == "Text"
        and n.name.count(SEP) >= 2
        and n.name not in titles
    ]


def has_row(rows: list[str], lead: str, status: str | None = None) -> bool:
    return any(r.startswith(lead) and (status is None or f"{SEP}{status}{SEP}" in r) for r in rows)


def step(app: Any, s: Any, title: str) -> bool:
    """**Next**, then wait for the step titled ``title``."""
    found = ui.find(assistant(app, s), s.ASSIST_NEXT, "Button")
    if found is None or not found.enabled:
        return False
    app.press(found)
    try:
        ui.wait(lambda: ui.find(assistant(app, s), title, "Text"))
    except TimeoutError:
        return False
    return True


def only_usage(app: Any, s: Any, usage: str = USAGE) -> bool:
    """Tick only the usage ``usage`` on *What do you want to do?*."""
    from lianiq.packs.usage import USAGE_PROFILES
    from lianiq.ui.setup_assistant.step_usage import usage_text

    wanted = {usage_text(p): p.id == usage for p in USAGE_PROFILES}

    def boxes() -> list[Node]:
        return [n for n in assistant(app, s) if n.control_type == "CheckBox" and n.name in wanted]

    for box in boxes():
        if box.enabled and bool(box.selected) != wanted[box.name]:
            app.press(box)
    try:
        ui.wait(lambda: (f := boxes()) and all(bool(b.selected) == wanted[b.name] for b in f))
    except TimeoutError:
        return False
    return True


def languages(app: Any, s: Any) -> bool:
    """German in *First language*, Mandarin (Simplified) in *Second language*."""
    lists = ((s.ASSIST_LANG_FIRST, name(GERMAN)), (s.ASSIST_LANG_SECOND, name(MANDARIN)))

    def item(owner: str, wanted: str) -> Node | None:
        return next(
            (
                n
                for n in assistant(app, s)
                if n.visible and n.control_type == "ListItem" and n.name == wanted
                and owner in n.parents
            ),
            None,
        )  # fmt: skip

    for owner, wanted in lists:
        found = item(owner, wanted)
        if found is None:
            return False
        if not found.selected:
            app.press(found)
    try:
        ui.wait(lambda: all((item(o, w) or Node("", "")).selected for o, w in lists))
    except TimeoutError:
        return False
    return True


def assistant_import(app: Any, s: Any, pack_id: str, lead: str, folder: Path) -> str:
    """Readiness row **Get…** › the pack dialog's import (``packs_import``) › *Ready*."""
    definition = packs_import.pack(pack_id)
    get = next(
        (
            n
            for n in assistant(app, s)
            if n.control_type == "Button" and n.enabled and n.name == s.PACK_GET
            and n.description.startswith(lead)
        ),
        None,
    )  # fmt: skip
    if get is None:
        return "get-not-shown"
    app.press(get)
    try:
        ui.wait(lambda: app.window_nodes(definition.model))
    except TimeoutError:
        return "details-not-opened"
    reason = packs_import._accept_licence(app, s, definition) or packs_import._choose_folder(
        app, s, definition.model, folder
    )
    if reason is not None:
        return reason
    try:
        ui.wait(lambda: app.window_nodes(definition.model) is None)
        ready = lambda: has_row(review_rows(assistant(app, s), s), lead, s.ASSIST_REVIEW_READY)
        ui.wait(ready, ui.MODEL_TIMEOUT_S)
    except TimeoutError:
        return "not-ready"
    return "ready"


# Listen page ---------------------------------------------------------------------------


def rows(nodes: list[Node]) -> list[str]:
    return e14.rows(nodes)


def parts(text: str, source: str, target: str) -> tuple[str, str]:
    """(source text, outcome) of a row; the display text (heading, source, outcome) too."""
    head, sep, out = text.rpartition(f". {name(target)}: ")
    if sep:
        return head.partition(f", {name(source)}: ")[2], out
    lines = text.splitlines() or [""]
    return (lines[1] if len(lines) >= 3 else ""), lines[-1]


def direction_ok(text: str, source: str, target: str) -> bool:
    """The row has ``source`` as its source and ``target`` as its target language."""
    head, sep, _out = text.rpartition(f". {name(target)}: ")
    if sep:
        return f", {name(source)}: " in head
    return (text.splitlines() or [""])[0].endswith(f"· {name(source)}")


def busy(text: str, s: Any) -> bool:
    return text.endswith((s.LISTEN_RECOGNIZING, s.LISTEN_TRANSLATING))


def translated(text: str, source: str, target: str, s: Any) -> bool:
    out = parts(text, source, target)[1].strip()
    return bool(out) and not out.startswith(e14._pending(s))


def settle(app: Any, s: Any, count: int, enough: Callable[[list[str]], bool]) -> list[str]:
    """The rows after index ``count`` once ``enough`` holds, none is in progress and the list
    has not changed for ``SETTLE_S`` (``TimeoutError`` after the model timeout)."""
    last: dict[str, Any] = {"rows": None, "since": 0.0}

    def probe() -> list[str] | None:
        current, now = rows(app.nodes()), time.monotonic()
        if current != last["rows"]:
            last.update(rows=current, since=now)
            return None
        new = current[count:]
        quiet = now - last["since"] >= SETTLE_S
        return new if quiet and new and enough(new) and not any(busy(t, s) for t in new) else None

    return ui.wait(probe, ui.MODEL_TIMEOUT_S)


def in_order(sources: list[str], expected: tuple[str, ...]) -> bool:
    """Each recognised source text is closest to the fixture sentence at its position."""

    def norm(text: str) -> str:
        return "".join(c for c in text.casefold() if c.isalnum())

    def best(text: str) -> int:
        ratios = [difflib.SequenceMatcher(None, norm(text), norm(e)).ratio() for e in expected]
        return ratios.index(max(ratios))

    return len(sources) == len(expected) and all(best(t) == i for i, t in enumerate(sources))


def remember(ctx: Any, texts: list[str], source: str, target: str) -> list[str]:
    """Row texts, their source texts and outcomes into the secrets and the screenshot needles;
    returns the parts (for the privacy scans)."""
    found = [p.strip() for t in texts for p in parts(t, source, target)]
    kept = ctx.state.setdefault("transcripts", [])
    for text in [*texts, *found]:
        if text and text not in kept:
            kept.append(text)
        if len(text) >= MIN_SECRET and text not in ctx.secrets:
            ctx.secrets.append(text)
    return [p for p in found if len(p) >= MIN_SECRET]


def listening(app: Any, s: Any) -> bool:
    nodes = app.nodes()
    state = ui.shows(nodes, s.LISTEN_STATE_LISTENING) or ui.shows(nodes, s.LISTEN_STATE_PROCESSING)
    return state and ui.shows(nodes, s.SESSION_RUNNING.format(mode=s.NAV_LISTEN))


def start(app: Any, s: Any, checks: list[Check], name_: str) -> bool:
    """**Start listening** and wait until the page listens (model readiness)."""
    found = ui.find(app.nodes(), s.LISTEN_START, "Button")
    if found is None or not found.enabled:
        checks.append(check(name_, False, "not-enabled"))
        return False
    app.press(found)
    return ui.waited(checks, name_, lambda: listening(app, s), ui.MODEL_TIMEOUT_S)


def idle(nodes: list[Node], s: Any) -> bool:
    return e14._idle(nodes, s, s.SESSION_RUNNING.format(mode=s.NAV_LISTEN))


def combos(nodes: list[Node], s: Any) -> tuple[str | None, str | None]:
    labels = (s.LISTEN_SOURCE_LANGUAGE, s.LISTEN_TARGET_LANGUAGE)
    return tuple(e14._value(nodes, label_) for label_ in labels)  # type: ignore[return-value]


def shot(ctx: Any, app: Any, relative: str, name_: str) -> tuple[Check, Artifact]:
    """A masked screenshot: device combos, endpoint names, row needles and *Transcript*."""
    s = ui.strings()
    needles = ui.transcript_needles(ctx.state.get("transcripts", []))
    names = [*audio.endpoint_names(), *needles]
    combos_ = (s.LISTEN_MICROPHONE, s.NOTICE_MICROPHONE, s.NOTICE_SPEAKERS)
    fields = screens.TRANSCRIPT_FIELDS  # also the Listen *Transcript* list
    artifact, masked = screens.capture(ctx, app, relative, names, combos_, fields)
    return check(name_, True, f"masked={masked}"), artifact
