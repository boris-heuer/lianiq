from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_doctor_module():
    script = Path(__file__).parents[1] / "scripts" / "doctor.py"
    spec = importlib.util.spec_from_file_location("doctor", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def provision(root: Path, relative_paths: tuple[str, ...]) -> None:
    for relative in relative_paths:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")


def test_mandarin_voice_is_optional_for_default_doctor(tmp_path, monkeypatch) -> None:
    doctor = load_doctor_module()
    monkeypatch.setattr(doctor, "ROOT", tmp_path)
    provision(tmp_path, doctor.REQUIRED_MODEL_PATHS)

    assert all(doctor.check_models(require_mandarin_voice=False))


def test_operational_doctor_requires_user_provided_mandarin_pair(tmp_path, monkeypatch) -> None:
    doctor = load_doctor_module()
    monkeypatch.setattr(doctor, "ROOT", tmp_path)
    provision(tmp_path, doctor.REQUIRED_MODEL_PATHS)

    assert not all(doctor.check_models(require_mandarin_voice=True))

    provision(tmp_path, doctor.MANDARIN_VOICE_PATHS)

    assert all(doctor.check_models(require_mandarin_voice=True))
