"""Native crash logging must not itself crash the app (lianiq#69, WI-08).

On Windows faulthandler also reports exceptions that are handled later, such as the COM
error 0x8001010d that UI Automation clients (Narrator) raise and handle. Dumping all threads
for such a report walks other threads' frames while they run; natively this ended in an
access violation. On Windows only the reporting thread is dumped.
"""

from __future__ import annotations

import faulthandler
import logging
import sys
import threading

import pytest

from lianiq import logging_setup


@pytest.fixture
def enabled(monkeypatch: pytest.MonkeyPatch):
    """Record ``faulthandler.enable`` calls; restore every global configure_logging changes."""
    calls: list[dict] = []
    monkeypatch.setattr(faulthandler, "enable", lambda file, **kw: calls.append(kw))
    monkeypatch.setattr(faulthandler, "disable", lambda: None)
    monkeypatch.setattr(logging, "basicConfig", lambda **_kw: None)
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    monkeypatch.setattr(logging_setup, "_FAULT_LOG", None)
    yield calls
    if logging_setup._FAULT_LOG is not None:
        logging_setup._FAULT_LOG.close()


@pytest.mark.parametrize(
    ("platform", "all_threads"), [("win32", False), ("linux", True), ("darwin", True)]
)
def test_faulthandler_dumps_other_threads_only_off_windows(
    tmp_path, monkeypatch, enabled, platform, all_threads
) -> None:
    monkeypatch.setattr(sys, "platform", platform)

    logging_setup.configure_logging(tmp_path)

    assert enabled == [{"all_threads": all_threads}]
    assert (tmp_path / "native-crash.log").exists()
