"""Edge cases of the native evidence validator and redaction scan (CAP-0174 AC-01, AC-02).

Split from ``test_native_evidence.py`` to keep each file within the 12 KiB source limit.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from test_native_evidence import COMMIT, DIGEST, _data

from native_e2e.evidence.model import PHASE1_ROWS, validate
from native_e2e.evidence.redaction import Finding, scan


def _set(data: dict, keys: tuple, value: object) -> dict:
    target = data
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value
    return data


@pytest.mark.parametrize(
    ("keys", "value"),
    [
        (("commit",), COMMIT + "\n"),
        (("environment", "models_manifest_sha256"), DIGEST + "\n"),
        (("rows", 0, "artifacts", 0, "sha256"), DIGEST + "\n"),
        (("rows", 0, "artifacts", 0, "path"), "screens/e01.png\n"),
        (("rows", 0, "id"), "S-01\n"),
        (("rows", 0, "acs"), ["AC-15\n"]),
    ],
)
def test_a_trailing_newline_does_not_satisfy_an_anchored_pattern(keys: tuple, value) -> None:
    errors = validate(_set(_data(), keys, value))

    assert any("does not match" in error for error in errors), errors


@pytest.mark.parametrize("row_id", [["x"], {"a": 1}, 7, None])
def test_a_non_string_row_id_is_an_error_not_a_crash(row_id: object) -> None:
    data = _data()
    data["rows"][0]["id"] = row_id

    errors = validate(data)

    assert all(isinstance(error, str) for error in errors)
    assert any(error.startswith("$.rows[0].id") for error in errors)
    assert "open: S-01" in errors


def test_validate_survives_rows_of_the_wrong_shape() -> None:
    errors = validate({"rows": [{"id": ["x"]}, "S-01", None]})

    assert all(isinstance(error, str) for error in errors)
    assert [error for error in errors if error.startswith("open: ")] == [
        f"open: {row_id}" for row_id in PHASE1_ROWS
    ]


def test_duplicate_row_ids_are_rejected_once_each() -> None:
    data = _data()
    data["rows"] += [data["rows"][0], data["rows"][0], data["rows"][12]]

    assert validate(data) == ["$.rows: duplicate id S-01", "$.rows: duplicate id SHOT"]


@pytest.fixture
def tester(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USERNAME", "tester")
    monkeypatch.setenv("USERPROFILE", r"C:\Users\tester")


@pytest.mark.parametrize(
    "content",
    [
        "logged on as tester.",
        "logged on as tester",
        "user=tester-x",
        "tester-x",
        "(tester)",
        "Tester, welcome",
        '"user": "tester"',
        "by tester. Next",
    ],
)
def test_the_username_is_found_at_any_token_edge(
    tmp_path: Path, tester: None, content: str
) -> None:
    path = tmp_path / "log.txt"
    path.write_text(content, encoding="utf-8")

    assert scan([path], []) == [Finding(path.as_posix(), "username")]


@pytest.mark.parametrize(
    "content",
    [
        "native-tester-abc-1",
        "lianiq-tester",
        "tester.log",
        "a.tester",
        "testers",
        "untester",
        "tester2",
    ],
)
def test_the_username_inside_another_token_is_not_a_finding(
    tmp_path: Path, tester: None, content: str
) -> None:
    path = tmp_path / "log.txt"
    path.write_text(content, encoding="utf-8")

    assert scan([path], []) == []


def test_e2e_as_the_vm_user_keeps_tool_names_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("USERNAME", "e2e")
    monkeypatch.setenv("USERPROFILE", r"C:\Users\e2e")
    clean = tmp_path / "clean.txt"
    clean.write_text("native-e2e-abc-1 lianiq-e2e e2e.log win11-native-e2e@img\n", "utf-8")
    dirty = tmp_path / "dirty.txt"
    dirty.write_text("runner logged on as e2e.\n", encoding="utf-8")

    assert scan([clean, dirty], []) == [Finding(dirty.as_posix(), "username")]


def test_findings_keep_the_given_relative_path(
    tmp_path: Path, tester: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "s02.txt").write_text("tester", encoding="utf-8")

    assert scan([Path("logs/s02.txt")], []) == [Finding("logs/s02.txt", "username")]
