"""The pinned speech fixtures of ``native_e2e/fixtures/`` (spec §2.1.4; CAP-0174 AC-03).

``checked(name)`` returns the fixture's path only when the file exists and its SHA-256
equals the pin below; a row then plays it, else the row is ``blocked`` (``fixture-missing``).
``TEXTS`` holds what each fixture says: a row that plays one appends those texts to
``ctx.secrets`` (``remember``) so no stored artifact can carry them. Generator, voices and
licences: ``native_e2e/data/make_fixtures.py`` and ``native_e2e/fixtures/README.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from native_e2e.data.make_fixtures import FIXTURES
from native_e2e.evidence.sums import file_sha256

if TYPE_CHECKING:
    from native_e2e.context import RunContext

FOLDER = Path(__file__).resolve().parent / "fixtures"
# Mandarin fixtures (conv_zh_16k.wav, listen_zh_de_16k.wav) are not generated yet: see README.
PINNED: dict[str, str] = {
    "conv_de_16k.wav": "7874412d2d3972910cd2e73a5c486834d296af2996584a76e3b759cd09b5a858",
    "listen_de3_16k.wav": "99010a6c5e3fc064b8fcd1cca3f43c9962c884cf38c47d7ef7f61915b897d793",
    "listen_sentinel_16k.wav": "1af0f1e0c459eb90591ae4e7485e8aa09ab0b3e1afe5b55c269160aa1eb8bc27",
}
TEXTS: dict[str, tuple[str, ...]] = {
    name: tuple(text for _language, text in segments) for name, segments in FIXTURES.items()
}


def checked(name: str) -> Path | None:
    """The path of fixture ``name`` iff it is pinned, present and unchanged."""
    expected = PINNED.get(name)
    path = FOLDER / name
    if expected is None or not path.is_file():
        return None
    return path if file_sha256(path) == expected else None


def remember(ctx: RunContext, name: str) -> None:
    """Add the texts of fixture ``name`` to the redaction secrets."""
    for text in TEXTS.get(name, ()):
        if text not in ctx.secrets:
            ctx.secrets.append(text)
