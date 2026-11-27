"""The Conversation *Transcript* list as the UIA rows read it (paired-transcript spec §3.5).

Split from ``e03.py`` (file size); ``e03`` re-exports these names for E-10, E-15, E-19, E-37,
E-40 and the voice rows. ``view`` returns the shown row texts (``None`` without the list), the
list's one scroll value, the pair and the direction. Row texts are kept in memory only: the
rows store their SHA-256 (``digest``), and ``remember`` puts them into ``ctx.secrets``.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from native_e2e import screens
from native_e2e.context import RunContext
from native_e2e.rows import ui
from native_e2e.uia import Node

# Not in lianiq/ui/strings.py: the direction combo's accessible name (ROUTING_CONTROL_LABEL,
# ui/workspaces/pair_selection.py). The *Transcript* list is ``screens.TRANSCRIPT_FIELDS``.
LIST = screens.TRANSCRIPT_FIELDS[0]
DIRECTION_LABEL = "Conversation direction"
MIN_SECRET = 4  # shorter transcript lines are not useful scan needles
# A row's accessible text: "HH:MM:SS, {source}: {original}. {target}: {translation}".
_ROW = re.compile(r"^\d{2}:\d{2}:\d{2}, ([^:\n]+): (.*)\. ([^.:\n]+): (.*)$", re.DOTALL)
# Its display text: "HH:MM:SS · {source}", the original, then the translation.
_HEADING = re.compile(r"^\d{2}:\d{2}:\d{2} · (.+)$")


def panel(nodes: list[Node], title: str) -> Node | None:
    """The shown control named ``title`` that is not its heading label (E-13 text fields)."""
    return next(
        (
            node
            for node in nodes
            if node.visible and node.name == title and node.control_type not in ("Text", "")
        ),
        None,
    )


def transcript(nodes: list[Node]) -> Node | None:
    """The shown *Transcript* list."""
    return panel(nodes, LIST)


def items(nodes: list[Node]) -> list[str]:
    """The texts of the shown *Transcript* rows, in tree order."""
    return [
        node.name
        for node in nodes
        if node.visible and node.control_type == "ListItem" and LIST in node.parents
    ]


def turn_parts(item: str) -> tuple[str, str, str, str] | None:
    """(source name, original, target name, translation) of one row; ``None`` if unreadable.

    The display text names no target language; its target name is then empty."""
    match = _ROW.match(item)
    if match:
        return match.group(1), match.group(2), match.group(3), match.group(4)
    lines = item.splitlines()
    heading = _HEADING.match(lines[0]) if lines else None
    if heading and len(lines) >= 3:
        return heading.group(1), "\n".join(lines[1:-1]), "", lines[-1]
    return None


def panels(texts: list[str] | None) -> list[str]:
    """The rows as two labelled texts, originals then translations ("{name}: {text}" lines)."""
    parts = [p for p in (turn_parts(text) for text in texts or []) if p is not None]
    originals = "\n".join(f"{source}: {original}" for source, original, _, _ in parts)
    translations = "\n".join(
        f"{target}: {text}" if target else text for _, _, target, text in parts
    )
    return [originals, translations]


def _scroll(nodes: list[Node], field: Node | None) -> float | None:
    if field is None:
        return None
    if field.scroll is not None:
        return round(field.scroll, 3)
    # Without a UIA Scroll pattern: the scroll bar shows only once the rows overflow, so no
    # shown bar means nothing is scrolled (position 0).
    bars = [
        n for n in nodes if n.control_type == "ScrollBar" and n.visible and field.name in n.parents
    ]
    if not bars:
        return 0.0
    return round(bars[0].scroll, 3) if bars[0].scroll is not None else None


def view(nodes: list[Node], s: Any) -> dict[str, Any]:
    """The *Transcript* row texts (``None`` without the list), its scroll, pair, direction."""
    field = transcript(nodes)
    pair = ui.find(nodes, s.PAIR_LABEL, "ComboBox")
    direction = ui.find(nodes, DIRECTION_LABEL, "ComboBox")
    return {
        "texts": items(nodes) if field is not None else None,
        "scroll": _scroll(nodes, field),
        "pair": pair.value if pair is not None else None,
        "direction": direction.value if direction is not None else None,
    }


def has_turn(nodes: list[Node], s: Any) -> bool:
    """A row with an original and a translation is shown."""
    for text in view(nodes, s)["texts"] or []:
        parts = turn_parts(text)
        if parts is not None and parts[1].strip() and parts[3].strip():
            return True
    return False


def digest(texts: list[str]) -> str:
    return hashlib.sha256("\n".join(texts).encode("utf-8")).hexdigest()


def remember(ctx: RunContext, texts: list[str]) -> None:
    """The labelled originals and translations go to the state; rows and parts to secrets."""
    labelled = panels(texts)
    ctx.state["transcripts"] = labelled
    parts = [part for text in texts for part in (turn_parts(text) or ())[1::2]]
    lines = [line.strip() for text in [*texts, *parts] for line in [text, *text.splitlines()]]
    for line in [*lines, *ui.transcript_needles(labelled)]:
        if len(line) >= MIN_SECRET and line not in ctx.secrets:
            ctx.secrets.append(line)
