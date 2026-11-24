"""E-17 presses Download only while the S-04 block rule is in place (spec §2.1.9)."""

from __future__ import annotations

import pytest

from native_e2e import uia_app
from native_e2e.evidence.model import Check, Status
from native_e2e.rows import e17
from tests._native_fake_app import make_ctx


@pytest.mark.parametrize(
    "state", [None, {"checks": [Check("block-rule-added", Status.FAIL, "helper-timeout")]}]
)
def test_e17_is_blocked_without_the_s04_block_rule(tmp_path, monkeypatch, state) -> None:
    ctx = make_ctx(tmp_path)
    if state is not None:
        ctx.state["s04"] = state
    launched = []
    monkeypatch.setattr(uia_app, "launch", lambda *a, **k: launched.append(a))
    row = e17.run(ctx)
    assert (row.status, row.reason) == (Status.BLOCKED, "s04-block-rule-missing")
    assert launched == []
