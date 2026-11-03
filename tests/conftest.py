"""Shared pytest configuration."""

from __future__ import annotations

import gc

import pytest


@pytest.fixture(autouse=True)
def _collect_qt_garbage_on_the_main_thread():
    """Collect each test's cyclic garbage on the main thread.

    A closed window from one test can stay in a reference cycle. If Python's cyclic
    collector later runs on a worker thread (a Call Bridge lane or pipeline worker of
    another test), it destroys those Qt widgets off the GUI thread and the process
    aborts. Collecting here keeps Qt object destruction on the main thread.
    """
    yield
    gc.collect()
