"""Redact tool output before it is written into the artifact (CAP-0174 contract §5, §7.2).

``scrub`` replaces what ``native_e2e.evidence.redaction.scan`` looks for, so a stored log is
"redacted output": given secrets (endpoint names, test phrase) become ``<redacted>``,
endpoint identifiers ``<endpoint-id>``, absolute drive paths ``<path>`` and the user name
``<user>``. The scan still runs over every file afterwards; ``scrub`` only keeps expected
tool output from failing it. A planted canary is written after scrubbing, so the scan sees it.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable

from native_e2e.evidence.redaction import _USER

# A drive path runs to the next whitespace, quote or separator character.
_DRIVE_PATH = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/][^\s\"'<>|*?,;]*")
_ENDPOINT_ID = re.compile(r"\{0\.0\.[01]\.[^\s\"'<>|,;]*")


def scrub(text: str, secrets: Iterable[str]) -> str:
    """Return ``text`` with secrets, endpoint ids, drive paths and the user name replaced."""
    for secret in sorted({item for item in secrets if item}, key=len, reverse=True):
        text = re.sub(re.escape(secret), "<redacted>", text, flags=re.IGNORECASE)
    text = _ENDPOINT_ID.sub("<endpoint-id>", text)
    profile = os.environ.get("USERPROFILE", "")
    if profile:
        text = re.sub(re.escape(profile), "<path>", text, flags=re.IGNORECASE)
    text = _DRIVE_PATH.sub("<path>", text)
    username = os.environ.get("USERNAME", "")
    if username:
        text = re.sub(_USER.format(re.escape(username)), "<user>", text, flags=re.IGNORECASE)
    return text
