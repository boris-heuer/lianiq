"""Client of the allow-listed SYSTEM admin helper in the guest (CAP-0174 contract §1, §7.4).

Protocol of ``tools/native-e2e/guest/admin-helper.ps1``: the test user writes one request
``admin\\requests\\<id>.json`` = ``{"id", "verb", "args"}`` (written under a dot name, then
renamed, so the helper never reads a partial file); the helper deletes it and writes
``admin\\results\\<id>.json`` = ``{"id", "verb", "ok", "value", "error"}``. ``request`` waits
for that result with ``wait_for`` and raises ``TimeoutError`` without one. It sends any verb,
because S-04 must prove that the helper rejects an unlisted one; ``admin_request`` is the
typed form for the three allow-listed verbs.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from native_e2e.context import IMAGE_ROOT
from native_e2e.uia import wait_for

ADMIN_DIR = IMAGE_ROOT / "admin"
DEFAULT_TIMEOUT_S = 30.0
Verb = Literal["firewall-block-app", "firewall-unblock-app", "wfp-count"]


@dataclass(frozen=True)
class AdminResult:
    ok: bool
    value: str | None
    error: str | None = None  # the helper's rejection reason, for example "verb-not-allowed"


def request(
    verb: str, *args: str, timeout_s: float = DEFAULT_TIMEOUT_S, poll_s: float = 0.25
) -> AdminResult:
    root = Path(ADMIN_DIR)
    request_id = uuid.uuid4().hex
    staging = root / "requests" / f".{request_id}.tmp"
    payload = {"id": request_id, "verb": verb, "args": list(args)}
    staging.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(staging, root / "requests" / f"{request_id}.json")
    result = root / "results" / f"{request_id}.json"
    wait_for(result.is_file, timeout_s, poll_s)
    data = json.loads(result.read_text(encoding="utf-8-sig"))
    value = data.get("value")
    error = data.get("error")
    return AdminResult(
        data.get("ok") is True and data.get("id") == request_id,
        None if value is None else str(value),
        None if error is None else str(error),
    )


def admin_request(verb: Verb, *args: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> AdminResult:
    return request(verb, *args, timeout_s=timeout_s)
