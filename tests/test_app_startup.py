"""CAP-0171 WI-03 start-up: offline flags, pack recovery and the first-run rule (C §9)."""

from __future__ import annotations

import ast
import json
import tomllib
from pathlib import Path

import pytest

import lianiq.config as config_module
from lianiq import app
from lianiq.packs.recovery import RecoveryFailed

ROOT = Path(__file__).resolve().parents[1]
ENGINES = ("lianiq.stt", "lianiq.translation", "lianiq.tts", "lianiq.pipeline", "lianiq.meeting")


def test_ac22_offline_flags_are_set_before_any_engine_import() -> None:
    tree = ast.parse((ROOT / "lianiq/app.py").read_text(encoding="utf-8"))
    flags: dict[str, int] = {}
    first_lianiq_import = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Subscript):
            target = node.targets[0]
            if ast.unparse(target.value) == "os.environ" and ast.unparse(node.value) == "'1'":
                flags[ast.literal_eval(target.slice)] = node.lineno
        module = node.module if isinstance(node, ast.ImportFrom) else None
        if module and module.startswith("lianiq") and first_lianiq_import is None:
            first_lianiq_import = node.lineno
    assert set(flags) == {"HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"}
    assert first_lianiq_import is not None and max(flags.values()) < first_lianiq_import
    imported = [n.module for n in tree.body if isinstance(n, ast.ImportFrom) and n.module]
    assert any(module.startswith(ENGINES) for module in imported)


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    default = tmp_path / "settings.json"
    default.write_text(config_module.DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"), "utf-8")
    local = tmp_path / "settings.local.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", default)
    monkeypatch.setattr(config_module, "LOCAL_CONFIG_PATH", local)
    monkeypatch.setattr(app, "LOCAL_CONFIG_PATH", local)
    return local


def test_ac31_upgrade_without_provisioning_is_completed_and_saved(settings: Path) -> None:
    settings.write_text('{"schema_version": 2, "ui": {"log_level": "DEBUG"}}', "utf-8")

    config, due = app.load_settings([])

    assert (config.provisioning.first_run, due) == ("completed", False)
    config.save()
    assert json.loads(settings.read_text("utf-8"))["provisioning"]["first_run"] == "completed"


def test_first_launch_is_due_unless_the_flag_is_given(settings: Path) -> None:
    config, due = app.load_settings([])
    assert (config.provisioning.first_run, due) == ("pending", True)
    assert app.load_settings([app.NO_SETUP_ASSISTANT])[1] is False
    assert not settings.exists()  # loading never writes


def test_a_stored_choice_is_kept(settings: Path) -> None:
    settings.write_text('{"schema_version": 2, "provisioning": {"first_run": "skipped"}}', "utf-8")
    config, due = app.load_settings([])
    assert (config.provisioning.first_run, due) == ("skipped", False)


def test_failed_recovery_does_not_stop_start_up() -> None:
    calls: list[str] = []

    class Installer:
        def recover(self) -> tuple[str, ...]:
            calls.append("recover")
            raise RecoveryFailed(("mt-a",), ("tts-a",))

    app.recover_packs(Installer())  # type: ignore[arg-type]
    assert calls == ["recover"]


def test_default_recovery_on_an_empty_project(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(app, "PROJECT_ROOT", tmp_path)
    app.recover_packs()
    assert list(tmp_path.iterdir()) == []


def test_frozen_builds_ship_the_builtin_catalog() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "huggingface-hub" not in " ".join(project["project"]["dependencies"])
    package_data = project["tool"]["setuptools"]["package-data"]
    assert package_data["lianiq.packs"] == ["builtin_catalog.json"]
    build = (ROOT / "scripts/build.ps1").read_text(encoding="utf-8")
    assert '--add-data "lianiq/packs/builtin_catalog.json;lianiq/packs"' in build


def test_frozen_builds_ship_the_call_bridge_checklist() -> None:
    """The Call Bridge checklist link resolves to <app>/docs in a packaged build (lianiq#25)."""
    build = (ROOT / "scripts/build.ps1").read_text(encoding="utf-8")
    assert r"'dist\lianiq\docs'" in build
    assert "'call-bridge-operator-setup.md'" in build
