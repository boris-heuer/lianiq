"""Static checks of the ``native-e2e`` workflow (CAP-0174 AC-05, AC-09 static half, §6.1).

The workflow runs only on the self-hosted VM runner, so it never runs here. These checks pin
the security boundary: dispatch-only, environment approval, read-only token, SHA-pinned
actions, a dedicated runner label, the S-01 branch-containment check before any project
code, and the redaction gate before the upload.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
WORKFLOW = WORKFLOWS / "native-e2e.yml"
TEXT = WORKFLOW.read_text(encoding="utf-8") if WORKFLOW.is_file() else ""
DATA = yaml.safe_load(TEXT) if TEXT else {}
JOBS = DATA.get("jobs", {}) if isinstance(DATA, dict) else {}
JOB = next(iter(JOBS.values()), {}) if len(JOBS) == 1 else {}
STEPS = JOB.get("steps", [])
PINNED = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}$")


def triggers() -> dict:
    # YAML 1.1 reads the bare key ``on`` as boolean True.
    value = DATA.get("on", DATA.get(True))
    return value if isinstance(value, dict) else {}


def step(step_id: str) -> dict:
    matches = [item for item in STEPS if item.get("id") == step_id]
    assert len(matches) == 1, f"exactly one step with id {step_id}"
    return matches[0]


def index(step_id: str) -> int:
    return STEPS.index(step(step_id))


def uses_index(action: str) -> int:
    found = [n for n, item in enumerate(STEPS) if str(item.get("uses", "")).startswith(action)]
    assert len(found) == 1, f"exactly one {action} step"
    return found[0]


def test_the_workflow_is_dispatch_only_with_the_contract_inputs() -> None:
    assert WORKFLOW.is_file()
    assert set(triggers()) == {"workflow_dispatch"}
    inputs = triggers()["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"commit", "capability", "work_item", "plant_redaction_canary"}
    assert inputs["commit"]["required"] is True and inputs["commit"]["type"] == "string"
    for name in ("capability", "work_item"):
        assert inputs[name].get("required", False) is False
        assert inputs[name]["type"] == "string"
    canary = inputs["plant_redaction_canary"]
    assert canary["type"] == "boolean" and canary["default"] is False
    assert "pull_request_target" not in TEXT and "schedule:" not in TEXT


def test_the_token_is_read_only_and_no_secret_is_referenced() -> None:
    assert DATA["permissions"] == {"contents": "read"}
    assert "permissions" not in JOB or JOB["permissions"] == {"contents": "read"}
    assert "secrets." not in TEXT and "secrets[" not in TEXT
    assert "github.token" not in TEXT and "GITHUB_TOKEN" not in TEXT


def test_every_action_is_pinned_by_full_commit_sha() -> None:
    uses = [item["uses"] for item in STEPS if "uses" in item]
    assert uses, "the workflow uses checkout and upload-artifact"
    assert [value for value in uses if not PINNED.match(value)] == []
    assert {value.split("@")[0] for value in uses} == {
        "actions/checkout",
        "actions/upload-artifact",
    }


def test_the_job_needs_the_environment_and_the_dedicated_runner_label() -> None:
    assert len(JOBS) == 1
    environment = JOB["environment"]
    name = environment["name"] if isinstance(environment, dict) else environment
    assert name == "native-e2e"
    assert JOB["runs-on"] == ["self-hosted", "windows", "win11-native-e2e"]
    assert isinstance(JOB.get("timeout-minutes"), int) and JOB["timeout-minutes"] <= 180
    assert DATA["concurrency"]["cancel-in-progress"] is False


def test_no_other_workflow_uses_the_native_runner_label() -> None:
    others = [
        path.name
        for path in sorted(WORKFLOWS.glob("*.y*ml"))
        if path != WORKFLOW and "win11-native-e2e" in path.read_text(encoding="utf-8")
    ]
    assert others == []


def test_inputs_never_reach_a_script_by_expression() -> None:
    # Script injection: inputs go through env, never ``${{ inputs.* }}`` inside ``run:``.
    for item in STEPS:
        script = item.get("run", "")
        assert "${{" not in script, item.get("name")


def test_the_checkout_is_the_exact_commit_with_full_history_and_no_credentials() -> None:
    checkout = STEPS[uses_index("actions/checkout")]
    assert checkout["with"] == {
        "ref": "${{ inputs.commit }}",
        "fetch-depth": 0,
        "persist-credentials": False,
    }
    first = STEPS[0]
    assert first.get("run") and uses_index("actions/checkout") > 0
    assert "-cnotmatch '^[0-9a-f]{40}\\z'" in first["run"]
    assert "Get-Command git" in first["run"]


def test_the_first_step_allows_only_plain_identifiers_as_optional_inputs() -> None:
    script = STEPS[0]["run"]
    loop = "foreach ($value in @($env:NATIVE_E2E_CAPABILITY, $env:NATIVE_E2E_WORK_ITEM)) {"
    guard = "if ($value -and $value -cnotmatch '^[A-Za-z0-9._-]{1,64}\\z') { Stop-Run 'input-not-allowed' }"
    assert loop in script and guard in script
    assert script.index(loop) < script.index(guard)
    assert script.index("function Stop-Run") < script.index(loop)


def test_s01_branch_containment_runs_before_any_project_code() -> None:
    s01 = step("s01")
    script = s01["run"]
    assert "git for-each-ref --contains $env:NATIVE_E2E_COMMIT" in script
    assert "refs/remotes/origin/" in script
    assert "git rev-parse HEAD" in script
    assert "commit-not-in-repository-branch" in script
    assert "Where-Object { $_ -and $_ -ne 'refs/remotes/origin/HEAD' }" in script
    guard = (
        "if ($LASTEXITCODE -ne 0 -or $head -cne $env:NATIVE_E2E_COMMIT -or $branches.Count -eq 0) {"
    )
    block = script[script.index(guard) :]
    assert block.index("commit-not-in-repository-branch") < block.index("exit 1") < block.index("}")
    assert "GITHUB_STEP_SUMMARY" in block
    assert "if" not in s01 and "continue-on-error" not in s01  # never skipped or ignored
    assert uses_index("actions/checkout") < index("s01") < index("prepare")
    for item in STEPS[: index("s01") + 1]:
        assert not re.search(r"python|pip|native_e2e|\.py\b", item.get("run", "")), item["name"]
    assert "pip install --no-index --no-build-isolation --no-deps -e ." in step("prepare")["run"]


def test_the_rows_run_then_the_redaction_gate_then_the_upload() -> None:
    rows, gate = step("rows"), step("gate")
    upload_at = uses_index("actions/upload-artifact")
    upload = STEPS[upload_at]
    assert index("prepare") < index("rows") < index("gate") < upload_at
    assert upload_at == len(STEPS) - 1
    assert "-m', 'native_e2e', 'run'" in rows["run"]
    assert "-m native_e2e verify $env:NATIVE_E2E_OUT" in gate["run"]
    assert "exit $LASTEXITCODE" in rows["run"] and "exit $LASTEXITCODE" in gate["run"]
    assert gate["if"] == "${{ !cancelled() && steps.rows.outcome != 'skipped' }}"
    assert upload["if"] == "${{ !cancelled() && steps.gate.outcome == 'success' }}"
    assert not any("continue-on-error" in item for item in STEPS)
    assert upload["with"]["path"] == "${{ env.NATIVE_E2E_OUT }}"
    assert upload["with"]["if-no-files-found"] == "error"
    assert upload["with"]["name"] == (
        "native-e2e-${{ inputs.commit }}-${{ github.run_id }}-${{ github.run_attempt }}"
    )


def test_the_canary_and_optional_inputs_reach_the_row_runner_through_env() -> None:
    env = JOB["env"]
    assert env["NATIVE_E2E_COMMIT"] == "${{ inputs.commit }}"
    assert env["NATIVE_E2E_CAPABILITY"] == "${{ inputs.capability }}"
    assert env["NATIVE_E2E_WORK_ITEM"] == "${{ inputs.work_item }}"
    assert env["NATIVE_E2E_CANARY"] == "${{ inputs.plant_redaction_canary }}"
    script = step("rows")["run"]
    assert (
        "if ($env:NATIVE_E2E_CANARY -eq 'true') { $arguments += '--plant-redaction-canary' }"
        in (script)
    )
    assert "'--capability', $env:NATIVE_E2E_CAPABILITY" in script
    assert "'--work-item', $env:NATIVE_E2E_WORK_ITEM" in script
    assert "QT_QPA_PLATFORM" not in TEXT  # the rows need the real window


def test_the_workflow_and_native_text_files_fit_the_inline_publish_limit() -> None:
    files = [WORKFLOW, *sorted((ROOT / "native_e2e").rglob("*"))]
    files += sorted((ROOT / "tools" / "native-e2e").rglob("*"))
    large = [
        path.relative_to(ROOT).as_posix()
        for path in files
        if path.is_file() and "__pycache__" not in path.parts and path.stat().st_size > 32 * 1024
    ]
    assert large == []
    assert WORKFLOW.stat().st_size <= 22_000
