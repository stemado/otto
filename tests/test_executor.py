"""Tests for the workflow executor."""

import json
import os
import subprocess
import sys
from unittest.mock import patch

import pytest

from browser_scout.executor import (
    dry_run,
    mask_credential_value,
    needs_pre_monitoring,
    resolve_error_policy,
    resolve_variables,
)
from browser_scout.workflow import Workflow, WorkflowStep, WorkflowVariable


def _make_workflow(**kwargs) -> Workflow:
    """Helper to build a minimal Workflow for testing."""
    defaults = {
        "name": "test",
        "variables": {},
        "steps": [],
    }
    defaults.update(kwargs)
    return Workflow(**defaults)


# --- Variable resolution tests ---


def test_resolve_from_cli_args():
    workflow = _make_workflow(
        variables={"USERNAME": WorkflowVariable(type="credential", default="placeholder")},
        steps=[WorkflowStep(order=1, name="Type", action="type", selector="#user", value="${USERNAME}")],
    )
    resolved = resolve_variables(workflow, cli_vars={"USERNAME": "admin"})
    assert resolved.steps[0].value == "admin"


def test_resolve_from_env_var():
    workflow = _make_workflow(
        variables={"API_KEY": WorkflowVariable(type="string", default="placeholder")},
        steps=[WorkflowStep(order=1, name="Type", action="type", selector="#key", value="${API_KEY}")],
    )
    with patch.dict(os.environ, {"API_KEY": "env-value-123"}):
        resolved = resolve_variables(workflow, cli_vars={})
    assert resolved.steps[0].value == "env-value-123"


def test_resolve_from_default():
    workflow = _make_workflow(
        variables={"REPORT": WorkflowVariable(type="string", default="monthly-report")},
        steps=[WorkflowStep(order=1, name="Nav", action="navigate", value="https://example.com/${REPORT}")],
    )
    resolved = resolve_variables(workflow, cli_vars={})
    assert resolved.steps[0].value == "https://example.com/monthly-report"


def test_resolve_cli_overrides_env():
    workflow = _make_workflow(
        variables={"USERNAME": WorkflowVariable(type="credential", default="placeholder")},
        steps=[WorkflowStep(order=1, name="Type", action="type", selector="#user", value="${USERNAME}")],
    )
    with patch.dict(os.environ, {"USERNAME": "env-user"}):
        resolved = resolve_variables(workflow, cli_vars={"USERNAME": "cli-user"})
    assert resolved.steps[0].value == "cli-user"


def test_resolve_unresolved_variable_raises():
    workflow = _make_workflow(
        variables={"MISSING": WorkflowVariable(type="string")},
        steps=[WorkflowStep(order=1, name="Nav", action="navigate", value="${MISSING}")],
    )
    with pytest.raises(SystemExit) as exc_info:
        resolve_variables(workflow, cli_vars={})
    assert exc_info.value.code == 2


def test_resolve_multiple_vars_in_one_field():
    workflow = _make_workflow(
        variables={
            "HOST": WorkflowVariable(type="url", default="example.com"),
            "REPORT_PATH": WorkflowVariable(type="string", default="/reports"),
        },
        steps=[WorkflowStep(order=1, name="Nav", action="navigate", value="https://${HOST}${REPORT_PATH}")],
    )
    resolved = resolve_variables(workflow, cli_vars={})
    assert resolved.steps[0].value == "https://example.com/reports"


def test_resolve_var_in_selector():
    workflow = _make_workflow(
        variables={"REPORT_NAME": WorkflowVariable(type="string", default="Unum_Report")},
        steps=[WorkflowStep(order=1, name="Click", action="click", selector="[aria-label='${REPORT_NAME}']")],
    )
    resolved = resolve_variables(workflow, cli_vars={})
    assert resolved.steps[0].selector == "[aria-label='Unum_Report']"


def test_resolve_no_vars_passthrough():
    workflow = _make_workflow(
        steps=[WorkflowStep(order=1, name="Click", action="click", selector="#btn")],
    )
    resolved = resolve_variables(workflow, cli_vars={})
    assert resolved.steps[0].selector == "#btn"


# --- Error policy tests ---


def test_error_policy_step_overrides_global():
    assert resolve_error_policy(step_policy="continue", global_policy="stop") == "continue"


def test_error_policy_falls_back_to_global():
    assert resolve_error_policy(step_policy=None, global_policy="continue") == "continue"


def test_error_policy_retry_treated_as_stop():
    assert resolve_error_policy(step_policy="retry", global_policy="continue") == "stop"


def test_error_policy_global_retry_treated_as_stop():
    assert resolve_error_policy(step_policy=None, global_policy="retry") == "stop"


# --- Look-ahead tests ---


def test_needs_pre_monitoring_wait_for_download():
    next_step = WorkflowStep(order=2, name="Wait", action="wait_for_download")
    assert needs_pre_monitoring(next_step) is True


def test_needs_pre_monitoring_wait_for_response():
    next_step = WorkflowStep(order=2, name="Wait", action="wait_for_response", url_pattern="/api")
    assert needs_pre_monitoring(next_step) is True


def test_needs_pre_monitoring_regular_step():
    next_step = WorkflowStep(order=2, name="Click", action="click", selector="#btn")
    assert needs_pre_monitoring(next_step) is False


def test_needs_pre_monitoring_none():
    assert needs_pre_monitoring(None) is False


# --- Credential masking tests ---


def test_mask_credential_value():
    variables = {"PASSWORD": WorkflowVariable(type="credential")}
    assert mask_credential_value("${PASSWORD}", "s3cret", variables) == "****"


def test_mask_non_credential_value():
    variables = {"REPORT": WorkflowVariable(type="string")}
    assert mask_credential_value("${REPORT}", "monthly", variables) == "monthly"


def test_mask_no_variable_ref():
    variables = {}
    assert mask_credential_value("plain text", "plain text", variables) == "plain text"


# --- Dry-run tests ---


def test_dry_run_output(capsys):
    workflow = _make_workflow(
        variables={"USERNAME": WorkflowVariable(type="credential", default="admin")},
        steps=[
            WorkflowStep(order=1, name="Navigate", action="navigate", value="https://example.com"),
            WorkflowStep(order=2, name="Type user", action="type", selector="#user", value="${USERNAME}"),
        ],
    )
    resolved = resolve_variables(workflow, cli_vars={"USERNAME": "admin"})
    dry_run(resolved, original=workflow)

    lines = [json.loads(line) for line in capsys.readouterr().out.strip().split("\n")]
    assert lines[0]["dry_run"] is True
    assert lines[0]["total_steps"] == 2
    # Credential should be masked
    assert lines[2]["value"] == "****"


def test_dry_run_cli_valid_workflow(tmp_path):
    workflow_json = {
        "schema_version": "1.0",
        "name": "test-dry-run",
        "variables": {
            "USERNAME": {"type": "credential", "default": "testuser"},
        },
        "settings": {"headless": True},
        "steps": [
            {"order": 1, "name": "Navigate", "action": "navigate", "value": "https://example.com"},
            {"order": 2, "name": "Type user", "action": "type", "selector": "#user", "value": "${USERNAME}"},
        ],
    }
    workflow_file = tmp_path / "test.json"
    workflow_file.write_text(json.dumps(workflow_json))

    result = subprocess.run(
        [sys.executable, "-m", "browser_scout.executor", str(workflow_file),
         "--dry-run", "--var", "USERNAME=admin"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0

    lines = [json.loads(line) for line in result.stdout.strip().split("\n")]
    assert lines[0]["dry_run"] is True
    assert lines[0]["total_steps"] == 2
    # Credential should be masked
    assert lines[2]["value"] == "****"


def test_dry_run_cli_invalid_json(tmp_path):
    workflow_file = tmp_path / "bad.json"
    workflow_file.write_text("not json")

    result = subprocess.run(
        [sys.executable, "-m", "browser_scout.executor", str(workflow_file), "--dry-run"],
        capture_output=True, text=True,
    )
    assert result.returncode == 2


def test_dry_run_cli_missing_file():
    result = subprocess.run(
        [sys.executable, "-m", "browser_scout.executor", "/nonexistent/workflow.json", "--dry-run"],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
