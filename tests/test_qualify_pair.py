"""AC-12: the pair qualification kit ``scripts/qualify_pair.py`` (CAP-0181 WI-03)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from lianiq.domain import Transcript

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "qualification" / "en-zh-Hans.json"
PLANTED = "這"


def load_kit():
    spec = importlib.util.spec_from_file_location(
        "qualify_pair", ROOT / "scripts" / "qualify_pair.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeTranslator:
    """Tags the text with the edge; plants a Traditional character once and fails once."""

    def translate(self, text: str, edge) -> str:
        if text.startswith("Mr. Smith") and edge.key == "en>zh-Hans":
            return PLANTED + text
        if text.startswith("We cannot"):
            raise RuntimeError("engine failed")
        return f"[{edge.key}] {text}"


def git_status() -> str:
    return subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def rows(review: str) -> list[list[str]]:
    table = [line for line in review.splitlines() if line.startswith("| ")]
    return [line[2:-2].split(" | ") for line in table[1:]]


def test_the_kit_writes_the_review_sheet_and_summary_outside_the_repository(tmp_path) -> None:
    before = git_status()
    engines = SimpleNamespace(translator=FakeTranslator())

    code = load_kit().main(["--pair", "en:zh-Hans", "--out", str(tmp_path)], engines=engines)

    assert code == 0  # also with a failed sentence
    assert sorted(path.name for path in tmp_path.iterdir()) == ["review.md", "summary.json"]
    assert git_status() == before
    review = (tmp_path / "review.md").read_text("utf-8")
    header = next(line for line in review.splitlines() if line.startswith("| "))
    assert header.endswith("| Error | Accepted |")
    assert "Back-translation" in header and "Latency ms" in header
    table = rows(review)
    assert len(table) == 40
    assert all(row[-1] == "" for row in table)  # Accepted is left to the PO
    first = table[0]
    assert first[3].startswith("Mr. Smith") and first[4].startswith(PLANTED)
    assert first[5] == f"[zh-Hans>en] {PLANTED}{first[3]}" and first[6] == PLANTED
    assert all(row[6] == "" for row in table[1:])
    report = json.loads((tmp_path / "summary.json").read_text("utf-8"))
    assert report["sentences"] == 40 and report["failed"] == 1
    assert report["traditional_flags"] == 1
    assert report["directions"]["en>zh-Hans"]["count"] == 20
    assert report["directions"]["zh-Hans>en"]["tags"]["names"] == 4
    assert report["directions"]["en>zh-Hans"]["median_mt_ms"] is not None
    assert report["peak_memory_bytes"] > 0


def test_audio_runs_voice_recognition_and_translation(tmp_path) -> None:
    def synthesize_pcm(text, language):
        return np.full(2_205, 1_000, dtype=np.int16), 22_050

    def transcribe(samples, rate, language):
        assert rate == 16_000 and samples.size == 1_600
        return Transcript(f"heard {language}", language, 1.0, 0.1)

    engines = SimpleNamespace(
        translator=FakeTranslator(),
        synthesizer=SimpleNamespace(synthesize_pcm=synthesize_pcm),
        recognizer=SimpleNamespace(transcribe=transcribe),
    )
    args = ["--pair", "zh-Hans:en", "--out", str(tmp_path), "--audio"]

    assert load_kit().main(args, engines=engines) == 0

    assert "| heard en |" in (tmp_path / "review.md").read_text("utf-8")
    report = json.loads((tmp_path / "summary.json").read_text("utf-8"))
    assert report["audio"] is True
    assert report["directions"]["zh-Hans>en"]["median_stt_ms"] is not None


def test_the_output_folder_defaults_outside_and_never_inside_the_repository() -> None:
    kit = load_kit()

    assert not kit.default_out().resolve().is_relative_to(ROOT)
    with pytest.raises(SystemExit):
        kit.main(["--pair", "en:zh-Hans", "--out", str(ROOT / "out")], engines=object())
    assert not (ROOT / "out").exists()


def test_the_sentence_set_is_tagged_and_simplified_only() -> None:
    sentences = json.loads(FIXTURE.read_text("utf-8"))["sentences"]
    traditional = load_kit().TRADITIONAL_ONLY

    assert Counter(item["language"] for item in sentences) == {"en": 20, "zh-Hans": 20}
    for language in ("en", "zh-Hans"):
        tags = Counter(item["tag"] for item in sentences if item["language"] == language)
        assert set(tags) == {"names", "numbers", "negation", "general"}
        assert min(tags["names"], tags["numbers"], tags["negation"]) >= 4
    for item in sentences:
        if item["language"] == "zh-Hans":
            item["text"].encode("gb2312")  # Simplified script only
            assert not set(item["text"]) & traditional
    for char in traditional:  # no listed character is also Simplified
        with pytest.raises(UnicodeEncodeError):
            char.encode("gb2312")
