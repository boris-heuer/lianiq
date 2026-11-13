"""Receipt, redaction scan, ``SHA256SUMS`` and the upload gate (CAP-0174 contract §3, §7).

``finalize`` ends ``run``: it writes ``junit.xml``, plants the AC-14 canary when asked
(after every log was scrubbed, so the scan must find it), scans every file with the run's
secrets, writes ``native-evidence.json`` with the scan result, scans the receipt too, writes
``SHA256SUMS`` and appends the row table to the job summary. Exit code: 2 when the scan found
anything, else 0 only when every Phase 1 row is ``pass`` or ``pending``, else 1.

``verify`` is the workflow's redaction gate before the upload and the reviewer's check of a
downloaded artifact: the receipt validates (open rows are reported, not errors), it records
a clean scan, ``SHA256SUMS`` verifies and a re-scan with the fixed secrets finds nothing.
Output names files relative to the artifact root, pattern classes and check names only.
"""

from __future__ import annotations

import json
import platform
import uuid
from collections.abc import Iterable, Mapping
from pathlib import Path

from native_e2e.context import RunContext, default_secrets
from native_e2e.evidence.model import PHASE1_ROWS, Receipt, Row, Status, validate
from native_e2e.evidence.redaction import PNG_SIGNATURE, Finding, scan
from native_e2e.evidence.sums import verify_sums, write_sums
from native_e2e.summary import append, row_table, write_junit

RECEIPT = "native-evidence.json"
JUNIT = "junit.xml"
CANARY = "logs/redaction-canary.txt"
FINDINGS, ROWS_NOT_GREEN, CLEAN = 2, 1, 0


def scan_tree(root: Path, secrets: Iterable[str], only: str | None = None) -> list[Finding]:
    """Scan every file below ``root`` (or one); findings name files relative to ``root``."""
    files = [root / only] if only else sorted(p for p in root.rglob("*") if p.is_file())
    findings = scan(files, list(secrets))
    return [
        Finding(Path(item.file).relative_to(root).as_posix(), item.pattern_class)
        for item in findings
    ]


def _environment(ctx: RunContext) -> dict[str, str]:
    recorded = ctx.state.get("environment")
    if recorded:
        return dict(recorded)
    # S-01 did not get that far: the receipt then fails the schema and is never uploaded.
    return {
        "windows_build": "unknown",
        "image": "unknown",
        "python": platform.python_version(),
        "models_manifest_sha256": "unknown",
        "audio": "virtual (VB-Cable A)",
    }


def _screens(root: Path) -> int:
    return sum(1 for p in (root / "screens").glob("*.png") if p.read_bytes()[:8] == PNG_SIGNATURE)


def _write_receipt(ctx, rows, findings, capability, work_item) -> Receipt:
    files = sum(1 for p in ctx.out.rglob("*") if p.is_file() and p.name != RECEIPT)
    receipt = Receipt(
        commit=ctx.commit,
        workflow_run=ctx.workflow_run,
        environment=_environment(ctx),
        rows=rows,
        redaction_scan={
            "status": "findings" if findings else "clean",
            "pattern_classes": sorted({item.pattern_class for item in findings}),
            "files_scanned": files + 1,  # the receipt itself is scanned as well
            "screens_masked": int(ctx.state.get("screens_masked", 0)),
        },
        capability=capability or None,
        work_item=work_item or None,
    )
    (ctx.out / RECEIPT).write_text(receipt.to_json(), encoding="utf-8", newline="\n")
    return receipt


def finalize(
    ctx: RunContext,
    rows: Mapping[str, Row],
    *,
    capability: str | None,
    work_item: str | None,
    plant_canary: bool,
    summary: Path | None,
) -> int:
    ordered = tuple(rows[row_id] for row_id in PHASE1_ROWS if row_id in rows)
    ctx.out.mkdir(parents=True, exist_ok=True)
    write_junit(ctx.out / JUNIT, ordered)
    secrets = list(ctx.secrets)
    if plant_canary:
        token = f"lianiq-redaction-canary-{uuid.uuid4().hex}"
        (ctx.out / CANARY).parent.mkdir(parents=True, exist_ok=True)
        (ctx.out / CANARY).write_text(token + "\n", encoding="utf-8")
        secrets.append(token)
    findings = scan_tree(ctx.out, secrets)
    receipt = _write_receipt(ctx, ordered, findings, capability, work_item)
    own = scan_tree(ctx.out, secrets, only=RECEIPT)
    if own and not findings:
        receipt = _write_receipt(ctx, ordered, own, capability, work_item)
    findings += own
    write_sums(ctx.out)
    table = row_table(receipt.to_dict(), findings)
    print(table)
    append(summary, table)
    if findings:
        return FINDINGS
    green = {Status.PASS, Status.PENDING}
    complete = len(ordered) == len(PHASE1_ROWS)
    return CLEAN if complete and all(row.status in green for row in ordered) else ROWS_NOT_GREEN


def verify(root: Path, summary: Path | None = None) -> int:
    errors: list[str] = []
    opens: list[str] = []
    try:
        data = json.loads((root / RECEIPT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
        errors.append(f"receipt: {RECEIPT} missing or unreadable")
    if isinstance(data, dict):
        for item in validate(data):
            (opens if item.startswith("open: ") else errors).append(item)
        if data.get("redaction_scan", {}).get("status") != "clean":
            errors.append("redaction: the run's scan recorded findings")
    elif data is not None:
        errors.append("receipt: not a JSON object")
    errors += [f"sums: {item}" for item in verify_sums(root)]
    findings = scan_tree(root, default_secrets()) if root.is_dir() else []
    errors += [f"redaction: {item.file} ({item.pattern_class})" for item in findings]
    for line in errors + opens:
        print(line)
    verdict = "passed" if not errors else f"failed ({len(errors)} problems); nothing is uploaded"
    print(f"Redaction gate {verdict}; {len(opens)} open rows.")
    append(summary, f"### Redaction gate\n\n{verdict.capitalize()}; {len(opens)} open rows.")
    return 0 if not errors else 1
