"""C-05, C-06, C-09 keep no output line, and a failed junction swap is restored (AC-05, AC-08)."""

from __future__ import annotations

import _winapi
import json

import pytest

from native_e2e import models_swap, proc
from native_e2e.context import RunContext
from native_e2e.rows import c05, s04

LINE = "Deutsch: Guten Morgen -> 早上好"  # what self_test.py prints: a transcript


@pytest.fixture
def ctx(tmp_path) -> RunContext:
    image_root, models = tmp_path / "image", tmp_path / "image-models"
    image_root.mkdir()
    models.mkdir()
    (image_root / "image.json").write_text(json.dumps({"models_dir": str(models)}), "utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    context = RunContext("a" * 40, tmp_path / "out", repo, image_root=image_root)
    context.temp = tmp_path / "temp"
    models_swap.repoint(repo / "models", models)
    return context


@pytest.mark.parametrize("row", ["c05", "c06", "c09"])
def test_no_stdout_line_reaches_the_written_log(monkeypatch, ctx, row) -> None:
    result = proc.ToolResult(0, f"{LINE}\nOK\n", False)
    monkeypatch.setattr(proc, "run_tool", lambda args, cwd, timeout_s: result)
    monkeypatch.setattr(s04, "count_since", lambda ctx, since: 0)
    written = getattr(c05, row)(ctx)
    text = (ctx.out / written.artifacts[0].path).read_text("utf-8")
    assert "Guten" not in text and "OK" not in text
    assert text.startswith("output_sha256=") and "duration_s=" in text


def test_a_failed_create_junction_still_restores_the_image_junction(monkeypatch, ctx) -> None:
    real = _winapi.CreateJunction
    calls: list[str] = []

    def create(target: str, link: str) -> None:
        calls.append(target)
        if len(calls) == 1:
            raise OSError("junction refused")
        real(target, link)

    monkeypatch.setattr(_winapi, "CreateJunction", create)
    with pytest.raises(OSError), models_swap.scratch_models(ctx, "g1"):
        pytest.fail("the block must not run")
    assert models_swap.points_to(ctx.repo / "models", models_swap.image_models(ctx))
