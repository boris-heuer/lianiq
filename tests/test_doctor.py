"""``scripts/doctor.py`` reports readiness per capability of the configured pair (WI-07, S-02)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from lianiq.config import AppConfig

DE_VOICE = "models/piper/de_DE-thorsten-medium.onnx"
# WI-09: the Mandarin voice is a sherpa-onnx model directory.
ZH_VOICE = "models/sherpa/vits-icefall-zh-aishell3"
ZH_VOICE_FILES = (
    "model.onnx",
    "lexicon.txt",
    "tokens.txt",
    "phone.fst",
    "date.fst",
    "number.fst",
    "new_heteronym.fst",
    "rule.far",
)


def load_doctor_module():
    script = Path(__file__).parents[1] / "scripts" / "doctor.py"
    spec = importlib.util.spec_from_file_location("doctor", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def provision(root: Path, *relative_paths: str) -> None:
    for relative in relative_paths:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")


def provision_models(root: Path) -> None:
    """The repository default layout without the user-provided Mandarin voice (data D-01)."""
    provision(
        root,
        "models/faster-whisper-small/model.bin",
        "models/opus-mt-de-zh/config.json",
        "models/opus-mt-zh-de/config.json",
        DE_VOICE,
        f"{DE_VOICE}.json",
    )


@pytest.fixture
def doctor(tmp_path, monkeypatch):
    module = load_doctor_module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    return module


def test_s02_doctor_prints_readiness_per_capability(doctor, tmp_path, capsys) -> None:
    provision_models(tmp_path)

    checks = doctor.check_capabilities(AppConfig(), require_voices=False)

    assert all(checks)
    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        "[OK ] Language pair: de (German) ↔ zh-Hans (Mandarin (Simplified))",
        "[OK ] recognition de (German): installed",
        "[OK ] recognition zh-Hans (Mandarin (Simplified)): installed",
        "[OK ] translation de>zh-Hans (German → Mandarin (Simplified)): installed",
        "[OK ] translation zh-Hans>de (Mandarin (Simplified) → German): installed",
        "[OK ] voice de (German): installed",
        (
            "[WARN] voice zh-Hans (Mandarin (Simplified)): missing; "
            "spoken output in this language stays unavailable"
        ),
    ]


def test_operational_doctor_requires_every_voice_of_the_pair(doctor, tmp_path, capsys) -> None:
    provision_models(tmp_path)

    assert not all(doctor.check_capabilities(AppConfig(), require_voices=True))
    assert "[MISSING] voice zh-Hans (Mandarin (Simplified)): missing" in capsys.readouterr().out

    # A voice directory without its rule archive is not usable.
    provision(tmp_path, *(f"{ZH_VOICE}/{name}" for name in ZH_VOICE_FILES[:-1]))
    assert not all(doctor.check_capabilities(AppConfig(), require_voices=True))
    assert "zh-Hans (Mandarin (Simplified)): missing voice files (rule.far)" in (
        capsys.readouterr().out
    )

    provision(tmp_path, f"{ZH_VOICE}/rule.far")
    assert all(doctor.check_capabilities(AppConfig(), require_voices=True))


def test_a_piper_voice_without_its_metadata_file_fails(doctor, tmp_path, capsys) -> None:
    provision_models(tmp_path)
    config = AppConfig()
    config.tts.voices["zh-Hans"] = "models/piper/zh_CN-other.onnx"
    config.tts.engines["zh-Hans"].engine = "piper"
    provision(tmp_path, "models/piper/zh_CN-other.onnx")

    assert not all(doctor.check_capabilities(config, require_voices=True))
    assert "zh-Hans (Mandarin (Simplified)): missing metadata file" in capsys.readouterr().out


def test_a_missing_reverse_edge_fails_and_is_named(doctor, tmp_path, capsys) -> None:
    provision_models(tmp_path)
    config = AppConfig()
    del config.translation.edges["zh-Hans>de"]

    assert not all(doctor.check_capabilities(config, require_voices=False))
    assert "[MISSING] translation zh-Hans>de (Mandarin (Simplified) → German): not_configured" in (
        capsys.readouterr().out
    )


def test_a_manifest_mismatch_is_invalid_even_for_an_optional_voice(
    doctor, tmp_path, capsys
) -> None:
    provision_models(tmp_path)
    provision(tmp_path, *(f"{ZH_VOICE}/{name}" for name in ZH_VOICE_FILES))
    good = hashlib.sha256(b"fixture").hexdigest()
    manifest = {
        "schema_version": 1,
        "artifacts": [
            {"path": "models/opus-mt-de-zh/config.json", "sha256": good},
            {"path": f"{ZH_VOICE}/model.onnx", "sha256": "0" * 64},
        ],
    }
    (tmp_path / "models" / "model-manifest.json").write_text(json.dumps(manifest), "utf-8")

    assert not all(doctor.check_capabilities(AppConfig(), require_voices=False))
    output = capsys.readouterr().out
    assert "[OK ] translation de>zh-Hans (German → Mandarin (Simplified)): validated" in output
    assert "[MISSING] voice zh-Hans (Mandarin (Simplified)): invalid" in output


def test_an_unusable_pair_fails_with_its_reason(doctor, capsys) -> None:
    config = AppConfig()
    config.languages.pair = ["de", "en"]

    assert doctor.check_capabilities(config, require_voices=False) == [False]
    assert "[MISSING] Language pair:" in capsys.readouterr().out


def test_main_reports_settings_and_exits_nonzero_without_models(doctor, capsys) -> None:
    assert doctor.main([]) == 1
    output = capsys.readouterr().out
    assert "[OK ] Settings: schema v2" in output
    assert "[MISSING] recognition de (German): missing" in output
