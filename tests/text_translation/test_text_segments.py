"""CAP-0172 contract §4: segmentation and join (AC-13, AC-14 unit halves)."""

from __future__ import annotations

import unicodedata

from lianiq.text_translation.segments import (
    SEGMENT_TOKEN_BUDGET,
    Segment,
    join_output,
    split_source,
)
from tests.text_translation._text_helpers import fake_tokens


def roundtrip(text: str, measure=fake_tokens) -> tuple[str, tuple[tuple[Segment, ...], ...]]:
    split = split_source(text, measure)
    joined = join_output(text.split("\n"), [[s.text for s in line] for line in split])
    return joined, split


def test_lines_keep_blank_lines_and_prefixes() -> None:
    text = "Erster Satz. Zweiter Satz!\n\n    Eingerückt? Ja.\n \t\n\tTab."
    joined, split = roundtrip(text)
    assert joined == text
    assert [[s.text for s in line] for line in split] == [
        ["Erster Satz.", "Zweiter Satz!"],
        [],
        ["Eingerückt?", "Ja."],
        [],
        ["Tab."],
    ]
    assert split[2][0].prefix == "    " and split[2][1].prefix == ""
    assert split[4][0].line == 4


def test_cjk_sentences_split_without_whitespace_and_join_without_spaces() -> None:
    joined, split = roundtrip("你好。今天天气很好！你呢？Hello. 再见。")
    assert [s.text for s in split[0]] == ["你好。", "今天天气很好！", "你呢？", "Hello.", "再见。"]
    assert joined == "你好。今天天气很好！你呢？Hello. 再见。"


def test_latin_terminators_need_whitespace_and_closers_stay() -> None:
    _, split = roundtrip('Version 1.5 kommt... bald. Er sagte "Ja." Dann ging er.')
    assert [s.text for s in split[0]] == [
        "Version 1.5 kommt...",
        "bald.",
        'Er sagte "Ja."',
        "Dann ging er.",
    ]


def test_arabic_question_mark_ends_a_sentence() -> None:
    text = "مرحبا؟ كيف حالك."
    joined, split = roundtrip(text)
    assert [s.text for s in split[0]] == ["مرحبا؟", "كيف حالك."]
    assert joined == text


def test_long_sentences_split_at_whitespace_or_commas_within_the_budget() -> None:
    latin = " ".join(f"wort{i}," if i % 7 == 6 else f"wort{i}" for i in range(300)) + "."
    joined, split = roundtrip(latin)
    assert len(split[0]) > 1
    assert all(fake_tokens(s.text) <= SEGMENT_TOKEN_BUDGET for s in split[0])
    assert joined == latin


def test_long_han_sentence_hard_cuts_and_joins_without_spaces() -> None:
    han = "汉" * 400 + "。"
    joined, split = roundtrip(han)
    assert [len(s.text) for s in split[0]] == [128, 128, 128, 17]
    assert joined == han


def test_ac14_combining_marks_are_never_split() -> None:
    text = "a" + "e\u0301" * 200  # 401 code points, no whitespace; cuts land on marks
    split = split_source(text, len)
    pieces = [s.text for s in split[0]]
    assert len(pieces) > 3
    assert all(len(piece) <= SEGMENT_TOKEN_BUDGET for piece in pieces)
    assert all(not unicodedata.combining(piece[0]) for piece in pieces)
    assert "".join(pieces) == text


def test_ac13_5000_characters_measure_within_budget_and_keep_layout() -> None:
    paragraph = " ".join(f"Satz {i} hat einige Wörter und endet hier." for i in range(14))
    han = "这是一个比较长的中文句子，用来测试分段。" * 8
    lines: list[str] = []
    while sum(len(line) + 1 for line in lines) < 5_200:
        lines += [paragraph, "", "    " + paragraph, han, "\t" + han, " "]
    text = "\n".join(lines)[:5_000].rstrip()
    joined, split = roundtrip(text)
    segments = [s for line in split for s in line]
    assert len(text) <= 5_000 and len(segments) > 40
    assert max(fake_tokens(s.text) for s in segments) <= SEGMENT_TOKEN_BUDGET
    assert joined == text  # line breaks, blank lines, prefixes; CJK joined without spaces
