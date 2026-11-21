"""The socket guard of the CAP-0171 pack tests: no test under ``tests/packs`` uses the network.

Every attempt is recorded and refused. The record matters because the installer turns
unexpected exceptions into ``InstallFailed``; tests that prove "no network call" (AC-10)
assert the record is empty instead of relying on the refusal alone.
"""

from __future__ import annotations

import socket

import pytest


@pytest.fixture(autouse=True)
def network_attempts():
    """Its own ``MonkeyPatch``, so a test's ``monkeypatch.undo()`` keeps the guard."""
    attempts: list[str] = []

    def refuse(name: str):
        def blocked(*args: object, **kwargs: object) -> None:
            attempts.append(name)
            raise ConnectionRefusedError(f"socket guard: {name} is blocked in pack tests")

        return blocked

    with pytest.MonkeyPatch.context() as guard:
        guard.setattr(socket.socket, "connect", refuse("connect"))
        guard.setattr(socket.socket, "connect_ex", refuse("connect_ex"))
        guard.setattr(socket, "create_connection", refuse("create_connection"))
        guard.setattr(socket, "getaddrinfo", refuse("getaddrinfo"))
        yield attempts
