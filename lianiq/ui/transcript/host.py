"""``TranscriptHost``: what a workspace gives its ``PairedTranscriptView`` (spec §3.2).

The replay members come from ``ReplayHost`` (``replay.py``, paired-transcript WI-03).
``workspace``, ``export_prefix`` and ``main_window`` (dialog parent, diagnostics, notices and
status bar) let the view show the existing export messages of that workspace.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from lianiq.languages.registry import LanguagePair
    from lianiq.transcript.turns import Turn
    from lianiq.ui.notices import Notice
    from lianiq.ui.shell.workspaces import WorkspaceId


class TranscriptHost(Protocol):
    workspace: WorkspaceId
    export_prefix: str  # the default file name: ``{export_prefix}-{date}.txt``

    @property
    def main_window(self): ...

    def pair_for_export(self) -> LanguagePair: ...

    def replay_block(self, turn: Turn) -> str | None:
        """``None`` when **Replay** is allowed, else the tooltip."""

    def replay(self, turn: Turn) -> None: ...

    def stop_playback(self) -> None: ...

    def playing(self) -> bool: ...

    def clear_session(self) -> None:
        """Stop the workspace's session when not idle, then clear the log."""

    def post_notice(self, notice: Notice) -> None: ...
