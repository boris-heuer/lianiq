"""Pair qualification kit (CAP-0181 §3.6): translate a synthetic sentence set offline.

``python scripts/qualify_pair.py --pair en:zh-Hans --out <folder>`` translates every sentence
of ``tests/fixtures/qualification/<pair>.json`` into the other pair language and back with
the configured engines, and writes ``review.md`` (the PO marks *Accepted*) and
``summary.json`` to ``--out``. Nothing is written inside the repository. ``--audio`` also
speaks each source with its voice (a noise fixture is mixed in at 10 dB SNR when present) and
records recognition text and latency. The exit code is 0 also when sentences fail.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from lianiq.languages.capabilities import DirectedEdge
from lianiq.languages.errors import LanguageContractError
from lianiq.languages.registry import BUILTIN_REGISTRY, LanguageRegistry, normalize_language_id

ROOT = Path(__file__).resolve().parents[1]

FIXTURES = ROOT / "tests" / "fixtures" / "qualification"
NOISE_GLOB = "tests/fixtures/**/noise*.wav"  # the CAP-0177 noise fixture, when present
SNR_DB = 10.0
SIMPLIFIED_SCRIPT = "hans"  # BCP 47 script subtag whose output is checked
# Traditional-only characters: none of them is part of the Simplified set (GB2312).
TRADITIONAL_ONLY = frozenset(
    "們這個國會說時來對為與書經業東車長開門問間關電話語號機點報買賣錢價貨運過還進遠選讓應當從"
    "發現實學體離難題頭認識寫讀聽見覺親歡樂氣萬億歲黨條統際續總習準標權樣檢據環員單團圖場壓處"
    "備復歷義顯驗鐘錯鍵陽隊階雖雙雞響頁須領風飛飯館馬驚魚鳥麼齊龍"
)


def default_out() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path(tempfile.gettempdir()) / "lianiq-qualification" / stamp


def traditional(text: str) -> str:
    return "".join(sorted({char for char in text if char in TRADITIONAL_ONLY}))


def checked(language: str) -> bool:
    return SIMPLIFIED_SCRIPT in language.lower().split("-")[1:]


def peak_memory_bytes() -> int | None:
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                    (name, ctypes.c_size_t)
                    for name in ("peak", "ws", "qpp", "qp", "qpn", "qn", "pf", "ppf")
                ]

            counters = Counters(cb=ctypes.sizeof(Counters))
            process = wintypes.HANDLE(-1)  # the current-process pseudo handle
            info = ctypes.windll.kernel32.K32GetProcessMemoryInfo
            if info(process, ctypes.byref(counters), counters.cb):
                return int(counters.peak)
            return None
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    except Exception:  # noqa: BLE001 - memory is informative only
        return None


def timed(call, *args):
    started = time.perf_counter()
    value = call(*args)
    return value, round((time.perf_counter() - started) * 1000, 1)


def spoken_samples(engines, text: str, language: str, noise):
    """The source spoken by its voice at 16 kHz, with noise at ``SNR_DB`` when given."""
    import numpy as np

    from lianiq.audio.resampler import convert_capture_audio

    pcm, rate = engines.synthesizer.synthesize_pcm(text, language)
    samples = convert_capture_audio(np.asarray(pcm, dtype=np.float32) / 32768.0, rate)
    if noise is not None and noise.size and samples.size:
        noise = np.resize(noise, samples.size)
        power = float(np.mean(samples**2)) / max(float(np.mean(noise**2)), 1e-12)
        samples = np.clip(samples + noise * np.sqrt(power / 10 ** (SNR_DB / 10)), -1, 1)
    return samples.astype(np.float32)


def load_noise():
    import wave

    import numpy as np

    from lianiq.audio.resampler import convert_capture_audio

    for path in sorted(ROOT.glob(NOISE_GLOB)):
        with wave.open(str(path), "rb") as wav:
            data = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
            data = data.reshape(-1, wav.getnchannels()) / 32768.0
            return path.name, convert_capture_audio(data, wav.getframerate())
    return None, None


def qualify(engines, pair, sentences, audio: bool = False) -> tuple[list[dict], str | None]:
    noise_name, noise = load_noise() if audio else (None, None)
    rows = []
    for number, item in enumerate(sentences, 1):
        source = normalize_language_id(item["language"])
        edge = DirectedEdge(source, pair.other(source))
        row = {"#": number, "tag": item["tag"], "direction": edge.key, "source": item["text"]}
        row |= {"translation": "", "back": "", "traditional": "", "mt_ms": None, "error": ""}
        try:
            row["translation"], row["mt_ms"] = timed(
                engines.translator.translate, item["text"], edge
            )
            reverse = DirectedEdge(edge.target, edge.source)
            row["back"] = engines.translator.translate(row["translation"], reverse)
            outputs = [row["translation"]] if checked(edge.target) else []
            outputs += [row["back"]] if checked(edge.source) else []
            row["traditional"] = traditional("".join(outputs))
            if audio:
                samples = spoken_samples(engines, item["text"], source, noise)
                heard, row["stt_ms"] = timed(engines.recognizer.transcribe, samples, 16_000, source)
                row["recognized"] = heard.text
                row["audio_translation"], row["audio_mt_ms"] = timed(
                    engines.translator.translate, heard.text, edge
                )
        except Exception as exc:  # noqa: BLE001 - a failed sentence is reported, not fatal
            row["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
    return rows, noise_name


def cell(value) -> str:
    return "" if value is None else str(value).replace("|", "\\|").replace("\n", " ")


def review_markdown(pair_key: str, rows: list[dict], audio: bool) -> str:
    columns = [
        ("#", "#"),
        ("Tag", "tag"),
        ("Direction", "direction"),
        ("Source", "source"),
        ("Translation", "translation"),
        ("Back-translation", "back"),
        ("Traditional", "traditional"),
        ("Latency ms", "mt_ms"),
    ]
    if audio:
        columns += [("Recognized", "recognized"), ("STT ms", "stt_ms")]
        columns += [("Audio translation", "audio_translation")]
    columns += [("Error", "error"), ("Accepted", None)]
    lines = [
        f"# Qualification review: {pair_key}",
        "",
        "Mark each row in *Accepted* (yes/no). Traditional lists the Traditional-only",
        "characters found in Simplified output.",
        "",
        "| " + " | ".join(title for title, _ in columns) + " |",
        "|" + "---|" * len(columns),
    ]
    for row in rows:
        values = [cell(row.get(key)) if key else "" for _, key in columns]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines) + "\n"


def median(values) -> float | None:
    values = [value for value in values if value is not None]
    return round(statistics.median(values), 1) if values else None


def summary(pair_key: str, rows: list[dict], audio: bool, noise: str | None) -> dict:
    directions = {}
    for key in dict.fromkeys(row["direction"] for row in rows):
        own = [row for row in rows if row["direction"] == key]
        tags: dict[str, int] = {}
        for row in own:
            tags[row["tag"]] = tags.get(row["tag"], 0) + 1
        directions[key] = {
            "count": len(own),
            "failed": sum(1 for row in own if row["error"]),
            "tags": tags,
            "traditional_flags": sum(1 for row in own if row["traditional"]),
            "median_mt_ms": median(row["mt_ms"] for row in own),
        }
        if audio:
            directions[key]["median_stt_ms"] = median(row.get("stt_ms") for row in own)
    return {
        "pair": pair_key,
        "sentences": len(rows),
        "failed": sum(1 for row in rows if row["error"]),
        "traditional_flags": sum(1 for row in rows if row["traditional"]),
        "median_mt_ms": median(row["mt_ms"] for row in rows),
        "directions": directions,
        "audio": audio,
        "noise_fixture": noise,
        "peak_memory_bytes": peak_memory_bytes(),
    }


def configured_engines(audio: bool):
    from lianiq.app import build_pipeline
    from lianiq.config import AppConfig

    pipeline = build_pipeline(AppConfig.load())
    return SimpleNamespace(
        translator=pipeline.text_translator(),
        recognizer=pipeline.speech_recognizer() if audio else None,
        synthesizer=pipeline.voice_synthesizer() if audio else None,
    )


def main(argv=None, engines=None, registry: LanguageRegistry = BUILTIN_REGISTRY) -> int:
    parser = argparse.ArgumentParser(description="Qualify a language pair on synthetic text.")
    parser.add_argument("--pair", required=True, metavar="SRC:TGT", help="e.g. en:zh-Hans")
    parser.add_argument("--out", type=Path, default=None, help="Default: a temp folder.")
    parser.add_argument("--audio", action="store_true", help="Also run voice → STT → MT.")
    args = parser.parse_args(argv)
    try:
        source, target = args.pair.split(":")
        pair = registry.pair(registry.get(source).id, registry.get(target).id)
    except (ValueError, LanguageContractError) as exc:
        parser.error(f"--pair: {exc}")
    out = (args.out or default_out()).resolve()
    if out.is_relative_to(ROOT):
        parser.error("--out must be outside the repository")
    pair_key = "-".join(pair.members)
    fixture = FIXTURES / f"{pair_key}.json"
    if not fixture.is_file():
        parser.error(f"no sentence set {fixture.name}")
    sentences = json.loads(fixture.read_text(encoding="utf-8"))["sentences"]
    rows, noise = qualify(engines or configured_engines(args.audio), pair, sentences, args.audio)
    out.mkdir(parents=True, exist_ok=True)
    (out / "review.md").write_text(review_markdown(pair_key, rows, args.audio), "utf-8")
    report = summary(pair_key, rows, args.audio, noise)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    (out / "summary.json").write_text(text, "utf-8")
    print(f"{len(rows)} sentences, {report['failed']} failed; review sheet: {out / 'review.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
