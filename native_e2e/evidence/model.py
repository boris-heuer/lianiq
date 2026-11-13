"""Evidence receipt ``lianiq-native-evidence/v1`` (CAP-0174 contract §1 and §7.1).

Portable and Qt-free. ``validate`` checks a receipt document against
``schema/native-evidence.v1.schema.json`` with a small validator for exactly the JSON Schema
keywords that file uses (``jsonschema`` is not in the lock), then reports each Phase 1 row
missing from ``rows[]`` as ``open: <row>``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from pathlib import Path

SCHEMA_ID = "lianiq-native-evidence/v1"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema" / "native-evidence.v1.schema.json"


class Status(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    BLOCKED = "blocked"
    PENDING = "pending"


class Method(StrEnum):
    NATIVE = "automated-native"
    VIRTUAL_DEVICE = "automated-virtual-device"
    MANUAL = "manual"


# Spec §2.3 order; a row id from this list that is missing from rows[] is open.
PHASE1_ROWS: tuple[str, ...] = (
    "S-01", "S-02", "S-03", "S-04", "S-05", "C-04", "E-01", "E-11", "E-03", "E-10",
    "E-12", "C-03", "SHOT", "T-01", "T-02", "T-03", "T-04",
)  # fmt: skip


@dataclass(frozen=True)
class Check:
    name: str
    result: Status
    detail: str | None = None

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {"name": self.name, "result": str(self.result)}
        if self.detail is not None:
            data["detail"] = self.detail
        return data


@dataclass(frozen=True)
class Artifact:
    path: str  # relative to the artifact root, "/"-separated
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "sha256": self.sha256}


@dataclass(frozen=True)
class Row:
    id: str
    acs: tuple[str, ...]
    method: Method
    status: Status
    checks: tuple[Check, ...]
    artifacts: tuple[Artifact, ...]
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "id": self.id,
            "acs": list(self.acs),
            "method": str(self.method),
            "status": str(self.status),
        }
        if self.reason is not None:
            data["reason"] = self.reason
        data["checks"] = [check.to_dict() for check in self.checks]
        data["artifacts"] = [artifact.to_dict() for artifact in self.artifacts]
        return data


@dataclass(frozen=True)
class Receipt:
    commit: str
    workflow_run: str
    environment: Mapping[str, str]
    rows: tuple[Row, ...]
    redaction_scan: Mapping[str, object]
    capability: str | None = None
    work_item: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": SCHEMA_ID,
            "capability": self.capability,
            "work_item": self.work_item,
            "commit": self.commit,
            "workflow_run": self.workflow_run,
            "environment": dict(self.environment),
            "rows": [row.to_dict() for row in self.rows],
            "redaction_scan": dict(self.redaction_scan),
            # The artifact is immutable after upload; PO sign-offs live in the consuming
            # capability's verification-report.md (contract §7.1).
            "human_signoffs": [],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"


def validate(receipt: Mapping[str, object]) -> list[str]:
    """Return schema errors, duplicate row ids, then ``open: <row>`` per missing Phase 1 row."""
    schema = _schema()
    errors = _check(receipt, schema, schema, "$")
    rows = receipt.get("rows") if isinstance(receipt, Mapping) else None
    ids: list[str] = []
    if isinstance(rows, list):
        ids = [
            row["id"] for row in rows if isinstance(row, Mapping) and isinstance(row.get("id"), str)
        ]
    duplicates = sorted({row_id for row_id in ids if ids.count(row_id) > 1})
    errors += [f"$.rows: duplicate id {row_id}" for row_id in duplicates]
    return errors + [f"open: {row_id}" for row_id in PHASE1_ROWS if row_id not in ids]


@cache
def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


_TYPES: dict[str, tuple[type, ...]] = {
    "object": (Mapping,),
    "array": (list, tuple),
    "string": (str,),
    "integer": (int,),
    "null": (type(None),),
}


def _is_type(value: object, name: str) -> bool:
    if name == "integer" and isinstance(value, bool):
        return False
    return isinstance(value, _TYPES[name])


def _check(value: object, node: Mapping, root: Mapping, at: str) -> list[str]:
    if "$ref" in node:
        target: Mapping = root
        for part in node["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        return _check(value, target, root, at)
    if "const" in node and value != node["const"]:
        return [f"{at}: must be {node['const']!r}"]
    if "enum" in node and value not in node["enum"]:
        return [f"{at}: {value!r} is not one of {node['enum']}"]
    if "type" in node:
        names = node["type"] if isinstance(node["type"], list) else [node["type"]]
        if not any(_is_type(value, name) for name in names):
            return [f"{at}: expected {' or '.join(names)}"]
    if isinstance(value, str):
        return _check_string(value, node, at)
    if _is_type(value, "integer") and value < node.get("minimum", value):
        return [f"{at}: below minimum {node['minimum']}"]
    if isinstance(value, Mapping):
        return _check_object(value, node, root, at)
    if isinstance(value, list | tuple):
        return _check_array(value, node, root, at)
    return []


def _check_string(value: str, node: Mapping, at: str) -> list[str]:
    if len(value) < node.get("minLength", 0):
        return [f"{at}: shorter than {node['minLength']}"]
    # ECMA-262 ``$`` (JSON Schema) matches only at the true end; Python's also before a final
    # "\n", so a trailing ``$`` is rewritten to ``\Z``.
    pattern = re.sub(r"(?<!\\)\$$", r"\\Z", node.get("pattern", ""))
    if "pattern" in node and not re.search(pattern, value):
        return [f"{at}: does not match {node['pattern']}"]
    return []


def _check_object(value: Mapping, node: Mapping, root: Mapping, at: str) -> list[str]:
    properties = node.get("properties", {})
    errors = [f"{at}: missing {key}" for key in node.get("required", []) if key not in value]
    for key, item in value.items():
        if key in properties:
            errors += _check(item, properties[key], root, f"{at}.{key}")
        elif node.get("additionalProperties", True) is False:
            errors.append(f"{at}: unexpected {key}")
    return errors


def _check_array(value: list | tuple, node: Mapping, root: Mapping, at: str) -> list[str]:
    errors = []
    if len(value) > node.get("maxItems", len(value)):
        errors.append(f"{at}: more than {node['maxItems']} items")
    if node.get("uniqueItems") and len({json.dumps(item) for item in value}) < len(value):
        errors.append(f"{at}: items are not unique")
    for index, item in enumerate(value):
        if "items" in node:
            errors += _check(item, node["items"], root, f"{at}[{index}]")
    return errors
