"""The diagnostics log and pattern redaction (CAP-0168 WI-03; contract.md §5): unit tests.

AC-27 (Unit): the export holds no transcript text, absolute path, username or endpoint ID,
redaction works by pattern (not a list of known values) and nothing touches the network.
The UI half (Copy / Export… / cancel / write error) is in ``tests/ui/test_shell_notices.py``.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from lianiq.diagnostics import DiagnosticsLog, redact

HOME = Path("C:/Users/jdoe")
USER = "jdoe"
NATIVE_ID = "windows-mmdevice:v1:capture:{0.0.1.00000000}.{6f1c2a3b-0d4e-4f5a-9b6c-7d8e9f0a1b2c}"
STALE_ID = "windows-mmdevice:v1:render:{0.0.0.00000000}.{11111111-2222-3333-4444-555555555555}"
DIGEST_ID = "audio-endpoint:v1:capture:3f9a0c1d#2"
RAW_ID = "{0.0.1.00000000}.{aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee}"

# What a reviewer greps the exported file for (E2E E-10).
ABSOLUTE_PATH = re.compile(r"\b[A-Za-z]:[\\/]|\\\\\w|(?<![\w:<])/(home|Users|tmp|var)\b")
ENDPOINT = re.compile(r"windows-mmdevice:|audio-endpoint:|\{\d+\.\d+\.\d+\.[0-9a-f]{8}\}")


def r(text: str) -> str:
    return redact(text, home=HOME, username=USER)


def test_endpoint_identities_become_stable_numbered_placeholders() -> None:
    text = f"capture {NATIVE_ID}; saved {STALE_ID}; again {NATIVE_ID}; {DIGEST_ID}; raw {RAW_ID}"
    assert r(text) == (
        "capture <endpoint-1>; saved <endpoint-2>; again <endpoint-1>; <endpoint-3>; "
        "raw <endpoint-4>"
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (r"model C:\Users\jdoe\lianiq\models\whisper-small", "model <path>/whisper-small"),
        ("model C:/Users/jdoe/lianiq/models/opus-mt-de-zh", "model <path>/opus-mt-de-zh"),
        (
            r"project D:\work\lianiq\config\settings.local.json",
            "project <path>/settings.local.json",
        ),
        (
            r"[Errno 13] Permission denied: 'E:\\ro\\diag.txt'",
            "[Errno 13] Permission denied: '<path>/diag.txt'",
        ),
        (r"share \\nas\exports\lianiq\log.txt", "share <path>/log.txt"),
        ("posix /home/jdoe/.cache/lianiq/x.bin", "posix <path>/x.bin"),
        ("home C:\\Users\\jdoe\\", "home <path>"),
        # Inner components with spaces (wave-1 B1).
        (r"model C:\Program Files\lianiq\models\whisper-small", "model <path>/whisper-small"),
        (
            r"model C:\Users\jdoe\OneDrive - Contoso GmbH\lianiq\models\opus done",
            "model <path>/opus done",
        ),
        (r"posix /home/jdoe/My Documents/lianiq/x.bin ok", "posix <path>/x.bin ok"),
        # A quoted path is one path, also with the doubled backslashes of an OSError repr.
        (
            r"[Errno 13] Permission denied: 'D:\\Shared Folder\\ro\\d.txt'",
            "[Errno 13] Permission denied: '<path>/d.txt'",
        ),
        (
            r"""saving "C:\Data Exports\my diagnostics.txt" failed""",
            'saving "<path>/my diagnostics.txt" failed',
        ),
        # The home spelling needs a boundary: a short name or a longer user name is not home.
        (r"temp C:\Users\JDOE~1\AppData\Local\Temp\x.txt", "temp <path>/x.txt"),
        (r"other C:\Users\jdoe2\x", "other <path>/x"),
        (r"repr 'C:\\Users\\jdoe\\lianiq\\a b\\c.txt'", "repr '<path>/c.txt'"),
        # Only the quoted-path branch handles a double space or a colon in a folder name.
        (r"'D:\\Team  Share\\ro\\d.txt'", "'<path>/d.txt'"),
        (r"'D:\Meeting: notes\ro\d.txt'", "'<path>/d.txt'"),
    ],
)
def test_absolute_paths_keep_only_their_last_component(text, expected) -> None:
    assert r(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        r"C:\Program Files\lianiq\models\whisper-small",
        r"C:\Users\jdoe\OneDrive - Contoso GmbH\lianiq\models\opus",
        r"'D:\\Shared Folder\\ro\\d.txt'",
        r"C:\Users\JDOE~1\AppData\Local\Temp\x.txt",
        r"C:\Users\jdoe2\x",
        r"'D:\\Team  Share\\ro\\d.txt'",
        r"'D:\Meeting: notes\ro\d.txt'",
    ],
)
def test_no_folder_name_survives_redaction(text) -> None:
    redacted = r(text)
    leaks = ("Program", "Files", "Contoso", "OneDrive", "Shared", "Folder", "JDOE", "jdoe2")
    for leaked in (*leaks, "Team", "Share", "Meeting", "notes"):
        assert leaked not in redacted, redacted
    assert "~" not in redacted  # a near-home folder never becomes a ``~`` path
    assert not ABSOLUTE_PATH.search(redacted), redacted


def test_the_username_is_replaced_but_ordinary_text_is_kept() -> None:
    assert r("user jdoe and JDOE-laptop") == "user <user> and <user>-laptop"
    assert r("jdoes stays; and/or 1/2; https://example.org/a; de>zh-Hans 1.25 s") == (
        "jdoes stays; and/or 1/2; https://example.org/a; de>zh-Hans 1.25 s"
    )


def test_redaction_is_by_pattern_not_by_known_values() -> None:
    # A path and an ID the redactor was never told about are still removed.
    other = (
        r"F:\Elsewhere\Profiles\Someone\voice.onnx windows-mmdevice:v1:render:{0.0.0.00000000}.{x}"
    )
    assert r(other) == "<path>/voice.onnx <endpoint-1>"


def session_log() -> DiagnosticsLog:
    """A session with endpoint IDs, a stale saved ID, model/project paths, a failed export."""
    log = DiagnosticsLog(home=HOME, username=USER)
    log.record("models", r"Speech recognition model: C:\Users\jdoe\lianiq\models\whisper-small")
    log.record("call-bridge", f"local_microphone: {NATIVE_ID}")
    log.record(
        "notice",
        f"blocking call-bridge.start-failed: Configured render endpoint is not available: {STALE_ID}",
    )
    log.record("turn", "4a7c-uuid de>zh-Hans 1.20 s")
    log.record(
        "export", r"Diagnostics export to C:\Users\jdoe\AppData\Local\Temp\ro\d.txt failed: denied"
    )
    log.record("project", "Settings file: /home/jdoe/src/lianiq/config/settings.local.json")
    return log


def test_ac27_the_export_has_no_path_username_or_endpoint_id() -> None:
    text = session_log().export_text()
    assert not ABSOLUTE_PATH.search(text), text
    assert not ENDPOINT.search(text), text
    assert USER not in text.lower()
    assert "<endpoint-1>" in text and "<endpoint-2>" in text
    assert "<path>/whisper-small" in text and "<path>/d.txt" in text
    lines = text.splitlines()
    assert len(lines) == 6 and all(
        re.match(r"\d{4}-\d\d-\d\dT[\d:]+[+-]\d\d:\d\d \[", x) for x in lines
    )


def test_the_log_is_bounded_and_keeps_its_entries_after_export() -> None:
    log = DiagnosticsLog(capacity=3, home=HOME, username=USER)
    for index in range(5):
        log.record("turn", f"turn {index}")
    assert [message for _when, _cat, message in log.entries()] == ["turn 2", "turn 3", "turn 4"]
    log.export_text()
    assert len(log.entries()) == 3  # export never clears the log
    assert DiagnosticsLog(home=HOME, username=USER).export_text() == ""


def test_the_log_redacts_any_text_with_its_home_and_user() -> None:
    log = DiagnosticsLog(home=HOME, username=USER)
    assert log.redact(r"C:\Users\jdoe\x\y.txt by jdoe") == "<path>/y.txt by <user>"


def test_ac27_diagnostics_has_no_network_code() -> None:
    source = Path(__file__).resolve().parents[1] / "lianiq" / "diagnostics.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in (
            node.names if isinstance(node, ast.Import) else [ast.alias(node.module or "")]
        )
    }
    assert imported <= {"__future__", "getpass", "re", "collections", "datetime", "pathlib"}
