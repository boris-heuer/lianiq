"""Shared state of one ``python -m native_e2e run`` (CAP-0174 contract §3, §5, §7.4).

``RunContext`` carries the commit, the artifact folder (``out``), the checkout (``repo``),
the guest image folder ``C:\\ProgramData\\lianiq-e2e`` (``image.json``, the S-01 run marker
under ``state\\``), the job's temp folder ``%TEMP%\\lianiq-e2e`` and the redaction secrets.
Rows record what later rows need in ``state`` (S-01 environment, S-03 backup, S-04 window,
SHOT reference). Every artifact path is relative to ``out``.
"""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from native_e2e.data.make_test_phrase import PHRASE
from native_e2e.evidence.model import Artifact
from native_e2e.evidence.sums import file_sha256
from native_e2e.scrub import scrub

IMAGE_ROOT = Path(r"C:\ProgramData\lianiq-e2e")
MARKER_NAME = "run-marker.json"
# Endpoint display names are on the privacy list (contract §7.2): never stored.
CABLE_NAMES = ("CABLE Input", "CABLE Output")


def default_secrets() -> list[str]:
    return [PHRASE, *CABLE_NAMES]


def default_temp() -> Path:
    return Path(tempfile.gettempdir()) / "lianiq-e2e"


@dataclass
class RunContext:
    commit: str
    out: Path
    repo: Path
    workflow_run: str = "local"
    image_root: Path = IMAGE_ROOT
    temp: Path = field(default_factory=default_temp)
    python: str = field(default_factory=lambda: sys.executable)
    secrets: list[str] = field(default_factory=default_secrets)
    state: dict[str, Any] = field(default_factory=dict)

    @property
    def marker(self) -> Path:
        return self.image_root / "state" / MARKER_NAME

    @property
    def local_settings(self) -> Path:
        return self.repo / "config" / "settings.local.json"

    def image(self) -> dict[str, Any]:
        """``image.json`` of the guest image; raises when it is missing or unreadable."""
        if "image" not in self.state:
            path = self.image_root / "image.json"
            self.state["image"] = json.loads(path.read_text(encoding="utf-8-sig"))
        return self.state["image"]

    def artifact(self, relative: str) -> Artifact:
        return Artifact(relative, file_sha256(self.out / relative))

    def write_log(self, relative: str, text: str) -> Artifact:
        """Write ``text`` scrubbed of every secret, path and user name; return the artifact."""
        target = self.out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(scrub(text, self.secrets), encoding="utf-8", newline="\n")
        return self.artifact(relative)
