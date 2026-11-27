"""Reads of the Conversation paired transcript for the window tests (paired-transcript WI-02).

The *Original*/*Translation* panels are gone; these give the same labelled lines from the
*Transcript* rows ("{source name}: {original}", "{target name}: {translation}").
"""

from __future__ import annotations

from lianiq.transcript.turns import TurnPart, turn_text


def view(window):
    return window.conversation.paired_view


def _pairs(window) -> list[list[str]]:
    registry = window.pipeline.registry
    rows = window.conversation.turns.rows
    return [turn_text(row, TurnPart.PAIR, registry).split("\n", 1) for row in rows]


def originals(window) -> list[str]:
    """One "{source name}: {original}" line per row, in row order."""
    return [pair[0] for pair in _pairs(window)]


def translations(window) -> list[str]:
    """One "{target name}: {translation}" line per row, in row order."""
    return [pair[1] for pair in _pairs(window)]


def list_at_end(window) -> bool:
    bar = view(window).list.verticalScrollBar()
    return bar.value() == bar.maximum()


def last_row_visible(window) -> bool:
    transcript = view(window)
    count = transcript.model.rowCount()
    if not count:
        return False
    rect = transcript.list.visualRect(transcript.model.index(count - 1))
    return rect.isValid() and transcript.list.viewport().rect().intersects(rect)
