"""Segmentation and join (contract.md §4, derivation).

``MarianTranslator.translate`` truncates its input, so a long source is translated per
sentence. Lines split at ``\\n``; a line splits after sentence terminators; a sentence above
``SEGMENT_TOKEN_BUDGET`` splits at the last whitespace or comma-like mark that fits, else at a
code-point boundary that is not before a combining mark.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

SEGMENT_TOKEN_BUDGET: Final = 128

_TERMINATORS: Final = frozenset(".!?…。！？؟")
_CJK_TERMINATORS: Final = frozenset("。！？")  # also end a sentence without whitespace
_CLOSERS: Final = frozenset("\"'”’»」』）)]】")  # stay with the sentence they close
_SOFT_BREAKS: Final = frozenset(",，、；;")


@dataclass(frozen=True, slots=True)
class Segment:
    line: int  # index of the source line
    prefix: str  # leading whitespace of the line, on its first segment only
    text: str  # one sentence or sub-sentence, stripped


def split_source(
    text: str, measure: Callable[[str], int], budget: int = SEGMENT_TOKEN_BUDGET
) -> tuple[tuple[Segment, ...], ...]:
    """Segments per source line; an empty or whitespace-only line has none."""
    result: list[tuple[Segment, ...]] = []
    for index, line in enumerate(text.split("\n")):
        body = line.lstrip()
        prefix = line[: len(line) - len(body)]
        pieces = [
            piece
            for sentence in _sentences(body.rstrip())
            for piece in _fit(sentence, measure, budget)
        ]
        result.append(
            tuple(
                Segment(index, prefix if position == 0 else "", piece)
                for position, piece in enumerate(pieces)
            )
        )
    return tuple(result)


def join_output(lines: Sequence[str], translated: Sequence[Sequence[str]]) -> str:
    """Rebuild the text: ``lines`` are the source lines, ``translated`` their sentences."""
    out: list[str] = []
    for line, sentences in zip(lines, translated, strict=True):
        if not line.strip():
            out.append(line)
            continue
        prefix = line[: len(line) - len(line.lstrip())]
        joined = ""
        for sentence in sentences:
            if not sentence:
                continue
            if joined and not _is_wide(joined[-1]):
                joined += " "
            joined += sentence
        out.append(prefix + joined)
    return "\n".join(out)


def _is_wide(character: str) -> bool:
    return unicodedata.east_asian_width(character) in ("W", "F")


def _sentences(body: str) -> list[str]:
    sentences: list[str] = []
    start = 0
    index = 0
    while index < len(body):
        character = body[index]
        if character in _TERMINATORS:
            end = index + 1
            while end < len(body) and body[end] in _CLOSERS:
                end += 1
            if character in _CJK_TERMINATORS or end == len(body) or body[end].isspace():
                sentences.append(body[start:end])
                start = index = end
                continue
        index += 1
    sentences.append(body[start:])
    return [sentence.strip() for sentence in sentences if sentence.strip()]


def _fit(sentence: str, measure: Callable[[str], int], budget: int) -> list[str]:
    pieces: list[str] = []
    rest = sentence
    while rest and measure(rest) > budget:
        cut = _cut(rest, measure, budget)
        piece = rest[:cut].strip()
        if piece:
            pieces.append(piece)
        rest = rest[cut:].strip()
    if rest:
        pieces.append(rest)
    return pieces


def _cut(text: str, measure: Callable[[str], int], budget: int) -> int:
    """The end of the longest leading piece of ``text`` that fits ``budget``."""
    low, high = 1, len(text) - 1  # the longest prefix length that still measures <= budget
    fits = 0
    while low <= high:
        middle = (low + high) // 2
        if measure(text[:middle]) <= budget:
            fits, low = middle, middle + 1
        else:
            high = middle - 1
    hard = _boundary(text, max(fits, 1))
    soft = max(
        (position for position in range(1, fits) if text[position].isspace()),
        default=0,
    )
    mark = max(
        (position + 1 for position in range(fits) if text[position] in _SOFT_BREAKS),
        default=0,
    )
    cut = max(soft, mark)
    if cut and text[:cut].strip() and measure(text[:cut].strip()) <= budget:
        return cut
    return hard


def _boundary(text: str, position: int) -> int:
    """Move ``position`` back so it is not before a combining mark (forward if it must)."""
    back = position
    while 0 < back < len(text) and unicodedata.combining(text[back]):
        back -= 1
    if back > 0:
        return back
    forward = position
    while forward < len(text) and unicodedata.combining(text[forward]):
        forward += 1
    return forward
