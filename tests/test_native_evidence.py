"""Portable native evidence library (CAP-0174 AC-01, AC-02, AC-03 and AC-06).

The library under ``native_e2e/evidence/`` runs in normal CI; the Windows-only row runner
does not. AC-06 is checked statically: the default ``pytest`` collects only ``tests/`` and
``ci.yml`` neither runs nor references the native workflow.
"""

from __future__ import annotations

import dataclasses
import json
import tomllib
from pathlib import Path

import pytest

from native_e2e.evidence.model import (
    PHASE1_ROWS,
    SCHEMA_ID,
    SCHEMA_PATH,
    Artifact,
    Check,
    Method,
    Receipt,
    Row,
    Status,
    validate,
)
from native_e2e.evidence.redaction import Finding, mask, scan
from native_e2e.evidence.sums import SUMS_NAME, verify_sums, write_sums

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "0123456789abcdef" * 2 + "01234567"
DIGEST = "ab" * 32


def _row(row_id: str) -> Row:
    method = Method.VIRTUAL_DEVICE if row_id in {"E-03", "E-11"} else Method.NATIVE
    return Row(
        id=row_id,
        acs=("AC-15",),
        method=method,
        status=Status.PASS,
        checks=(Check("present", Status.PASS),),
        artifacts=(Artifact("screens/e01.png", DIGEST),),
    )


def _receipt(rows: tuple[str, ...] = PHASE1_ROWS) -> Receipt:
    return Receipt(
        commit=COMMIT,
        workflow_run="123456-1",
        environment={
            "windows_build": "26100.4061",
            "image": "win11-native-e2e@img-1",
            "python": "3.12.10",
            "models_manifest_sha256": DIGEST,
            "audio": "virtual (VB-Cable A)",
        },
        rows=tuple(_row(row_id) for row_id in rows),
        redaction_scan={
            "status": "clean",
            "pattern_classes": [],
            "files_scanned": 3,
            "screens_masked": 1,
        },
        capability="CAP-0174",
        work_item="WI-03",
    )


def _data() -> dict:
    return json.loads(_receipt().to_json())


# AC-01 -----------------------------------------------------------------------------------


def test_phase1_rows_follow_the_spec_order() -> None:
    assert PHASE1_ROWS == (
        "S-01", "S-02", "S-03", "S-04", "S-05", "C-04", "E-01", "E-11", "E-03", "E-10",
        "E-12", "C-03", "SHOT", "T-01", "T-02", "T-03", "T-04",
    )  # fmt: skip


def test_a_complete_receipt_serialises_to_a_valid_document() -> None:
    receipt = _receipt()
    pending = dataclasses.replace(
        receipt.rows[-5],
        status=Status.PENDING,
        reason="PO sign-off required",
        checks=(Check("ssim", Status.PENDING, "0.981"),),
    )
    receipt = dataclasses.replace(receipt, rows=(*receipt.rows[:-5], pending, *receipt.rows[-4:]))

    data = json.loads(receipt.to_json())

    assert validate(data) == []
    assert data["schema"] == SCHEMA_ID == "lianiq-native-evidence/v1"
    assert data["human_signoffs"] == []
    assert [row["id"] for row in data["rows"]] == list(PHASE1_ROWS)
    assert data["rows"][12]["reason"] == "PO sign-off required"
    assert data["rows"][12]["checks"] == [{"name": "ssim", "result": "pending", "detail": "0.981"}]
    assert "reason" not in data["rows"][0]
    assert "detail" not in data["rows"][0]["checks"][0]
    assert data["rows"][7]["method"] == "automated-virtual-device"


def test_the_schema_file_sits_next_to_the_model() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert SCHEMA_PATH == ROOT / "native_e2e/evidence/schema/native-evidence.v1.schema.json"
    assert schema["properties"]["schema"]["const"] == SCHEMA_ID


def _drop_commit(data: dict) -> None:
    del data["commit"]


def _drop_environment_key(data: dict) -> None:
    del data["environment"]["image"]


def _unknown_status(data: dict) -> None:
    data["rows"][0]["status"] = "skipped"


def _unknown_check_result(data: dict) -> None:
    data["rows"][0]["checks"][0]["result"] = "ok"


def _unknown_method(data: dict) -> None:
    data["rows"][0]["method"] = "automated"


def _short_commit(data: dict) -> None:
    data["commit"] = COMMIT[:39]


def _upper_case_commit(data: dict) -> None:
    data["commit"] = COMMIT.upper()


def _signed_off(data: dict) -> None:
    data["human_signoffs"] = [{"by": "PO", "row": "SHOT"}]


def _absolute_artifact(data: dict) -> None:
    data["rows"][0]["artifacts"][0]["path"] = "C:/Users/e2e/screen.png"


def _extra_field(data: dict) -> None:
    data["operator"] = "someone"


@pytest.mark.parametrize(
    "corrupt",
    [
        _drop_commit,
        _drop_environment_key,
        _unknown_status,
        _unknown_check_result,
        _unknown_method,
        _short_commit,
        _upper_case_commit,
        _signed_off,
        _absolute_artifact,
        _extra_field,
    ],
)
def test_an_invalid_receipt_is_rejected(corrupt) -> None:
    data = _data()
    corrupt(data)

    errors = validate(data)

    assert errors
    assert not [error for error in errors if error.startswith("open: ")]


def test_a_missing_phase1_row_is_reported_as_open() -> None:
    rows = tuple(row_id for row_id in PHASE1_ROWS if row_id != "E-10")
    assert validate(json.loads(_receipt(rows).to_json())) == ["open: E-10"]


def test_a_non_object_receipt_is_rejected() -> None:
    assert validate([]) != []  # type: ignore[arg-type]


# AC-02 -----------------------------------------------------------------------------------


@pytest.fixture
def user_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USERNAME", "tester")
    monkeypatch.setenv("USERPROFILE", r"C:\Users\tester")


@pytest.mark.parametrize(
    ("content", "pattern_class"),
    [
        ("signed in as tester today", "username"),
        (r"profile c:\users\TESTER\AppData", "profile-path"),
        (r"opened C:/Users/other/AppData/x", "profile-path"),
        (r"saved to E:\exports\diag.txt", "drive-path"),
        ("endpoint {0.0.1.00000000}.{f00ba4}", "endpoint-id"),
        ("selected CABLE Output (VB-Audio Virtual Cable)", "secret"),
        ("heard: Guten Morgen, das ist ein Test.", "secret"),
        ("token canary-7f3a in the log", "secret"),
    ],
)
def test_scan_reports_each_pattern_class(
    tmp_path: Path, user_env: None, content: str, pattern_class: str
) -> None:
    path = tmp_path / "log.txt"
    path.write_text(content, encoding="utf-8")
    secrets = ["cable output (vb-audio virtual cable)", "Guten Morgen", "canary-7f3a"]

    findings = scan([path], secrets)

    assert Finding(path.as_posix(), pattern_class) in findings
    for finding in findings:
        assert content not in repr(finding)
        assert all(secret.casefold() not in repr(finding).casefold() for secret in secrets)


def test_scan_reports_a_wav_file_by_content_and_by_name(tmp_path: Path, user_env: None) -> None:
    riff = tmp_path / "capture.bin"
    riff.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt " + bytes(16))
    raw = tmp_path / "capture.pcm"
    raw.write_bytes(bytes(32))

    assert scan([riff, raw], []) == [
        Finding(riff.as_posix(), "audio-pcm"),
        Finding(raw.as_posix(), "audio-pcm"),
    ]


def test_scan_returns_one_finding_per_file_and_class(tmp_path: Path, user_env: None) -> None:
    path = tmp_path / "log.txt"
    path.write_text("tester X:\\a tester Y:\\b\n", encoding="utf-8")
    utf16 = tmp_path / "doctor.txt"
    utf16.write_text("run by tester", encoding="utf-16")

    assert scan([path, utf16], []) == [
        Finding(path.as_posix(), "drive-path"),
        Finding(path.as_posix(), "username"),
        Finding(utf16.as_posix(), "username"),
    ]
    assert [field.name for field in dataclasses.fields(Finding)] == ["file", "pattern_class"]


def test_clean_files_return_no_finding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USERNAME", "e2e")
    monkeypatch.setenv("USERPROFILE", r"C:\Users\e2e")
    path = tmp_path / "summary.txt"
    path.write_text(
        "artifact native-e2e-abc-1 from lianiq-e2e: https://github.com/x screens/a.png\n",
        encoding="utf-8",
    )

    assert scan([path], ["", "Guten Morgen"]) == []


def test_mask_fills_each_rectangle_so_no_source_pixel_remains() -> None:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRect
    from PySide6.QtGui import QColor, QImage

    image = QImage(30, 20, QImage.Format.Format_RGB32)
    for x in range(30):
        for y in range(20):
            image.setPixelColor(x, y, QColor(8 * x % 256, 12 * y % 256, 200))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()

    rects = [QRect(2, 3, 5, 4), QRect(26, 15, 10, 10)]
    masked = QImage.fromData(mask(bytes(data), rects), "PNG")

    assert (masked.width(), masked.height()) == (30, 20)
    for x in range(30):
        for y in range(20):
            inside = any(rect.contains(x, y) for rect in rects)
            colour = masked.pixelColor(x, y)
            expected = QColor(0, 0, 0) if inside else image.pixelColor(x, y)
            assert colour.rgb() == expected.rgb(), (x, y)


def test_mask_rejects_data_that_is_not_an_image() -> None:
    with pytest.raises(ValueError):
        mask(b"not a png", [])


# AC-03 -----------------------------------------------------------------------------------


def _artifact_folder(root: Path) -> None:
    (root / "screens").mkdir(parents=True)
    (root / "native-evidence.json").write_text("{}\n", encoding="utf-8")
    (root / "junit.xml").write_text("<testsuites/>\n", encoding="utf-8")
    (root / "screens" / "e01.png").write_bytes(b"\x89PNG fake")


def test_sums_list_every_other_file_and_verify(tmp_path: Path) -> None:
    _artifact_folder(tmp_path)

    sums_path = write_sums(tmp_path)

    assert sums_path == tmp_path / SUMS_NAME
    lines = sums_path.read_text(encoding="utf-8").splitlines()
    assert [line.split("  ", 1)[1] for line in lines] == [
        "junit.xml",
        "native-evidence.json",
        "screens/e01.png",
    ]
    assert all(len(line.split("  ", 1)[0]) == 64 for line in lines)
    assert verify_sums(tmp_path) == []


def test_verification_fails_when_any_file_changes(tmp_path: Path) -> None:
    _artifact_folder(tmp_path)
    write_sums(tmp_path)

    (tmp_path / "screens" / "e01.png").write_bytes(b"\x89PNG other")
    (tmp_path / "junit.xml").unlink()
    (tmp_path / "late.log").write_text("added later\n", encoding="utf-8")

    assert verify_sums(tmp_path) == [
        "missing: junit.xml",
        "changed: screens/e01.png",
        "unlisted: late.log",
    ]


def test_verification_fails_without_or_with_a_malformed_sums_file(tmp_path: Path) -> None:
    _artifact_folder(tmp_path)
    assert verify_sums(tmp_path) == [f"missing: {SUMS_NAME}"]

    (tmp_path / SUMS_NAME).write_text(f"{DIGEST}  ../outside.txt\nnot a line\n", encoding="utf-8")
    errors = verify_sums(tmp_path)
    assert "malformed: line 1" in errors
    assert "malformed: line 2" in errors


# AC-06 -----------------------------------------------------------------------------------


def test_default_pytest_collects_nothing_under_native_e2e() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    options = pyproject["tool"]["pytest"]["ini_options"]
    assert options["testpaths"] == ["tests"]
    assert "native_e2e" not in options.get("addopts", "")
    assert not {"python_files", "rootdir", "confcutdir"} & set(options)
    collectable = [
        path.relative_to(ROOT).as_posix()
        for pattern in ("test_*.py", "*_test.py", "conftest.py")
        for path in (ROOT / "native_e2e").rglob(pattern)
    ]
    assert collectable == []


def test_ci_workflow_stays_the_hosted_default_run() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for marker in ("native_e2e", "native-e2e", "win11-native-e2e", "self-hosted"):
        assert marker not in ci
    assert "runs-on: windows-latest" in ci
    assert "run: python -m pytest\n" in ci
