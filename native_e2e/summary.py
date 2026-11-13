"""Job summary row table and ``junit.xml`` of one run (CAP-0174 spec §2.2.1 step 5, AC-15).

Both are built from row ids, methods, statuses, fixed reason strings and artifact-relative
file names only, never from tool output, so nothing in them needs redaction. A Phase 1 row
missing from the receipt is listed as ``open``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from native_e2e.evidence.model import PHASE1_ROWS, Row, Status
from native_e2e.evidence.redaction import Finding

SHEET = "compare/application-ui.png"


def row_table(receipt: Mapping[str, Any], findings: Iterable[Finding]) -> str:
    rows = {row["id"]: row for row in receipt.get("rows", [])}
    environment = receipt.get("environment", {})
    lines = [
        "## native-e2e rows",
        "",
        (
            f"Commit `{receipt.get('commit')}` · run `{receipt.get('workflow_run')}` · "
            f"image `{environment.get('image')}`"
        ),
        "",
        "| Row | Method | Status | Reason |",
        "|---|---|---|---|",
    ]
    for row_id in PHASE1_ROWS:
        row = rows.get(row_id)
        if row is None:
            lines.append(f"| {row_id} | - | open | not run in this job |")
        else:
            reason = row.get("reason") or ""
            lines.append(f"| {row_id} | {row['method']} | {row['status']} | {reason} |")
    if rows.get("SHOT", {}).get("status") == str(Status.PENDING):
        lines += ["", f"**SHOT is pending: the PO must sign off `{SHEET}`.**"]
    scan = receipt.get("redaction_scan", {})
    found = list(findings)
    lines.append("")
    if found:
        lines.append("**Redaction scan found patterns; nothing is uploaded.**")
        lines += [f"- `{item.file}`: {item.pattern_class}" for item in found]
    else:
        lines.append(f"Redaction scan: clean ({scan.get('files_scanned')} files).")
    return "\n".join(lines) + "\n"


def append(path: Path | None, text: str) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(text + "\n")


def write_junit(path: Path, rows: Iterable[Row]) -> None:
    rows = list(rows)
    suite = ElementTree.Element("testsuite", name="native-e2e", tests=str(len(rows)))
    counts = {"failures": 0, "errors": 0, "skipped": 0}
    for row in rows:
        case = ElementTree.SubElement(suite, "testcase", classname="native_e2e", name=row.id)
        failed = ", ".join(c.name for c in row.checks if c.result is not Status.PASS)
        message = row.reason or failed or str(row.status)
        if row.status is Status.FAIL:
            ElementTree.SubElement(case, "failure", message=message)
            counts["failures"] += 1
        elif row.status is Status.BLOCKED:
            ElementTree.SubElement(case, "error", message=message)
            counts["errors"] += 1
        elif row.status is Status.PENDING:
            ElementTree.SubElement(case, "skipped", message=message)
            counts["skipped"] += 1
    for key, value in counts.items():
        suite.set(key, str(value))
    ElementTree.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)
