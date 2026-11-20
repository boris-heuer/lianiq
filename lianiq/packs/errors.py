"""Errors of offline language provisioning (CAP-0171 contract.md §10). Qt-free."""

from __future__ import annotations


class PackError(Exception):
    """Base class for every language-pack error."""


class _ReasonError(PackError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class PackCatalogError(_ReasonError):
    """The built-in catalog violates the load rules of contract.md §1."""


class UnknownPackError(PackError, LookupError):
    """A pack id is not in the catalog."""

    def __init__(self, pack_id: str) -> None:
        super().__init__(f"Unknown language pack: {pack_id!r}")
        self.pack_id = pack_id


class PackFileError(_ReasonError):
    """An import or a ``lianiq-pack.json`` fails contract.md §2; ``reason`` is shown as is."""


class ManifestError(_ReasonError):
    """The model manifest is unreadable when it must be used or written."""


class ConnectionUnavailable(PackError):
    """The transport cannot connect to ``host``."""

    def __init__(self, host: str) -> None:
        super().__init__(f"No connection to {host}")
        self.host = host


class InstallCancelled(PackError):
    """The user cancelled the job; nothing changed."""


class InstallFailed(_ReasonError):
    """Transfer, check, swap or remove failed; nothing changed."""


class JobBusy(PackError):
    """A pack job already runs."""


class PackInUse(PackError):
    """Update or remove of a pack that the active ``mode`` session uses."""

    def __init__(self, mode: str) -> None:
        super().__init__(f"The running {mode} session uses this pack")
        self.mode = mode


class InsufficientSpace(PackError):
    """Free disk space is below the bytes a job needs at its start."""

    def __init__(self, required: int, free: int) -> None:
        super().__init__(f"{required} bytes needed, {free} bytes free")
        self.required = required
        self.free = free
