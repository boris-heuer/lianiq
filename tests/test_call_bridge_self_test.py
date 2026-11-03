"""e2e row C-03: ``scripts/call_bridge_self_test.py --synthetic`` (AC-09)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from lianiq.config import AppConfig
from tests.languages.synthetic import QAA, QAB, synthetic_registry


def load_self_test_module():
    script = Path(__file__).parents[1] / "scripts" / "call_bridge_self_test.py"
    spec = importlib.util.spec_from_file_location("call_bridge_self_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_c03_synthetic_run_fixes_lanes_and_fails_closed_on_a_missing_voice(capsys) -> None:
    self_test = load_self_test_module()

    assert self_test.main(["--synthetic"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("PASS lanes: outbound=de>zh-Hans inbound=zh-Hans>de")
    assert lines[1] == "PASS fail-closed: missing voice Mandarin (Simplified)"


def test_c03_synthetic_run_follows_the_local_language_and_pair(capsys) -> None:
    self_test = load_self_test_module()
    config = AppConfig()
    config.languages.pair = [QAA, QAB]
    config.call_bridge.local_language = QAB

    assert self_test.run_synthetic(config, synthetic_registry()) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("PASS lanes: outbound=qab>qaa inbound=qaa>qab")
    assert lines[1] == "PASS fail-closed: missing voice Synthetic A"
