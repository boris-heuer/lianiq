"""E-11: a legacy device index is migrated to the cable's identity (contract §5, N-02).

Before launch the row writes ``config/settings.local.json`` from
``native_e2e/data/legacy-settings.template.json`` with ``audio.input_device`` set to the
PortAudio index of "CABLE Output" (no ``audio.*_policy``, ``*_endpoint_id`` or
``*_device_name`` key; schema 2, so the app keeps no ``settings.local.v1.json`` copy). It
launches the app, waits for the notice "Microphone set to '<name>' from your previous
settings", compares ``<name>`` with the cable's WASAPI name (the evidence stores only
``name_matches``), takes a masked screenshot, closes the app and reads the file:
``audio.input_device`` is ``null`` and both policy keys are set. S-03 backed the file up;
T-01 restores it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from native_e2e import audio, uia_app
from native_e2e.context import RunContext
from native_e2e.evidence.model import Check, Method, Row
from native_e2e.rows import ui
from native_e2e.rows.common import check, make_row

TEMPLATE = Path(__file__).resolve().parents[1] / "data" / "legacy-settings.template.json"
SCREEN = "screens/e11-migration-notice.png"


def legacy_settings(index: int) -> str:
    data = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    data["audio"]["input_device"] = index
    return json.dumps(data, indent=2) + "\n"


def migrated_pattern(s) -> re.Pattern[str]:
    prefix, suffix = s.DEVICE_MIGRATED.format(flow=s.NOTICE_MICROPHONE, name="\0").split("\0")
    return re.compile(re.escape(prefix) + "(.+)" + re.escape(suffix))


def _notice_name(nodes, pattern: re.Pattern[str]) -> str | None:
    for node in nodes:
        if not node.visible:
            continue
        for text in node.texts():
            match = pattern.search(text)
            if match:
                return match.group(1)
    return None


def _while_open(ctx: RunContext, app, expected: str | None) -> tuple[list[Check], list]:
    s = ui.strings()
    pattern = migrated_pattern(s)
    checks: list[Check] = []
    try:
        name = ui.wait_nodes(app, lambda nodes: _notice_name(nodes, pattern))
        checks.append(check("migration-notice-shown", True))
    except TimeoutError:
        name = None
        checks.append(check("migration-notice-shown", False, "timeout"))
    matches = name is not None and expected is not None and name == expected
    checks.append(check("name_matches", matches, f"name_matches: {str(matches).lower()}"))
    shot, artifact = ui.screenshot(ctx, app, SCREEN, "screenshot-masked")
    checks.append(shot)
    return checks, [artifact]


def _migrated(ctx: RunContext) -> list[Check]:
    try:
        settings = json.loads(ctx.local_settings.read_text(encoding="utf-8"))
        keys = settings.get("audio", {})
    except (OSError, ValueError, AttributeError) as error:
        detail = type(error).__name__
        return [check("input-device-null", False, detail), check("policy-keys-set", False)]
    return [
        check("input-device-null", "input_device" in keys and keys["input_device"] is None),
        check(
            "policy-keys-set",
            keys.get("input_policy") is not None and keys.get("output_policy") is not None,
        ),
    ]


def run(ctx: RunContext) -> Row:
    index = audio.legacy_input_index()
    expected = audio.wasapi_name(audio.CABLE_OUTPUT, "input")
    target = ctx.local_settings
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(legacy_settings(index), encoding="utf-8", newline="\n")
    checks = [check("legacy-settings-written", target.is_file(), f"input_device={index}")]
    app = uia_app.launch(ctx)
    try:
        shown, artifacts = _while_open(ctx, app, expected)
    finally:
        app.close()
    checks += shown + _migrated(ctx)
    return make_row(
        "E-11", checks, artifacts, reason="legacy-migration", method=Method.VIRTUAL_DEVICE
    )
