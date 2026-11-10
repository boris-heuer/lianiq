"""AC-35 docs: README, operator setup and troubleshooting describe the shell (CAP-0168 WI-06).

The docs quote the UI strings, so each check reads the text from ``lianiq.ui.strings``: a
renamed control or message fails here until the docs follow. Whitespace is normalised, so a
quoted string may wrap across lines.
"""

from __future__ import annotations

from pathlib import Path

from lianiq.config import AudioConfig
from lianiq.ui import strings

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
OPERATOR_SETUP = ROOT / "docs" / "call-bridge-operator-setup.md"
TROUBLESHOOTING = ROOT / "docs" / "troubleshooting.md"
NAME = "<name>"
DEVICE_KEYS = tuple(
    f"audio.{key}"
    for key in AudioConfig.__dataclass_fields__
    if key.endswith(("_policy", "_endpoint_id", "_device_name"))
)


def text(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def missing(path: Path, expected: list[str]) -> list[str]:
    content = text(path)
    return [item for item in expected if item not in content]


def test_the_six_device_keys_are_the_contract_keys() -> None:
    assert len(DEVICE_KEYS) == 6


def test_readme_describes_the_sidebar_strip_devices_and_diagnostics() -> None:
    expected = [
        strings.NAV_CONVERSATION,
        strings.NAV_TEXT_TRANSLATION,
        strings.NAV_LISTEN,
        strings.NAV_CALL_BRIDGE,
        strings.NAV_LANGUAGE_PACKS,
        strings.NAV_SETTINGS,
        strings.NAV_EXPERIMENTAL,
        strings.NAV_PLANNED,
        strings.STOP_ACTION,
        strings.SESSION_RUNNING.format(mode=strings.NAV_CONVERSATION),
        strings.SESSION_BUSY.format(mode=strings.NAV_CONVERSATION),
        strings.AUDIO_DEVICES,
        strings.DEVICE_FOLLOW_DEFAULT.format(name=NAME),
        strings.DEVICE_REFRESH,
        strings.DEVICE_TEST_MIC,
        strings.DEVICE_TEST_SPEAKERS,
        strings.DEVICE_UNAVAILABLE.format(name=NAME),
        strings.DEVICE_RECONNECT,
        strings.DEVICE_CHOOSE,
        strings.NOTICE_RETRY,
        strings.DIAG_TITLE,
        strings.DIAG_COPY,
        strings.DIAG_EXPORT,
        "Ctrl+1",
        "--evidence",
        "docs/troubleshooting.md",
        *DEVICE_KEYS,
    ]
    assert missing(README, expected) == []


def test_operator_setup_places_the_call_bridge_in_its_workspace() -> None:
    expected = [
        strings.NAV_CALL_BRIDGE,
        strings.NAV_EXPERIMENTAL,
        "Enable explicit four-endpoint routing",
        "Start call bridge",
        "Stop call bridge",
        strings.STOP_ACTION,
        strings.SESSION_BUSY.format(mode=strings.NAV_CONVERSATION),
        strings.SESSION_RUNNING.format(mode=strings.NAV_CALL_BRIDGE),
        strings.CONTINUES_LANE,
        f"Settings › {strings.AUDIO_DEVICES}",
        strings.DEVICE_REFRESH,
        "troubleshooting.md",
    ]
    assert missing(OPERATOR_SETUP, expected) == []


def test_troubleshooting_quotes_every_shell_notice_and_recovery() -> None:
    expected = [
        strings.NOTICE_BLOCKING,
        strings.NOTICE_WARNING,
        strings.NOTICE_INFO,
        strings.NOTICE_DISMISS,
        strings.NOTICE_MORE.format(count="N"),
        strings.MODE_UNAVAILABLE.format(items="…"),
        strings.SESSION_BUSY.format(mode=strings.NAV_CONVERSATION),
        strings.SESSION_BUSY.format(mode=strings.NAV_CALL_BRIDGE),
        strings.NAV_PLANNED_DESCRIPTION,
        strings.CONTINUES_NOT_STARTED,
        strings.DEVICE_UNAVAILABLE.format(name=NAME),
        strings.DEVICE_UNUSABLE.format(name=NAME, reason=strings.DEVICE_NO_INPUT),
        strings.DEVICE_FOLLOW_DEFAULT.format(name=NAME),
        strings.DEVICE_CHANGED.split(":")[0],
        strings.DEVICE_NO_SIGNAL.format(name=NAME),
        strings.DETAIL_DEVICE,
        strings.DEVICE_MIC_LOST.format(name=NAME),
        strings.DEVICE_SPEAKER_LOST.format(name=NAME),
        strings.DEVICE_RECONNECT_AFTER_STOP,
        strings.DEVICE_DEFAULT_NOW.format(flow="microphone", name=NAME),
        strings.DEVICE_MIGRATED.format(flow=strings.NOTICE_MICROPHONE, name=NAME),
        strings.DIAG_EXPORT_CANCELLED,
        strings.EXPORT_FAILED.format(reason="<reason>"),
        "<endpoint-N>",
        "<user>",
        "--evidence",
        *DEVICE_KEYS,
    ]
    assert missing(TROUBLESHOOTING, expected) == []
    # The evidence output format, with its two spaces (``sha256sum`` style).
    assert "`<sha256>  <file>`" in TROUBLESHOOTING.read_text(encoding="utf-8")


def test_troubleshooting_is_english_and_linked_from_readme_and_operator_setup() -> None:
    content = TROUBLESHOOTING.read_text(encoding="utf-8")
    assert content.startswith("# Troubleshooting\n")
    assert "](docs/troubleshooting.md)" in README.read_text(encoding="utf-8")
    assert "](troubleshooting.md)" in OPERATOR_SETUP.read_text(encoding="utf-8")
