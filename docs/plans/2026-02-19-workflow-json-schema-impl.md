# Workflow JSON Schema — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Pydantic models for the workflow JSON schema, a converter that transforms `SessionHistory` into a `Workflow`, and update `/export-workflow` to output JSON alongside Python scripts.

**Architecture:** New `workflow.py` module in `browser_scout/` with Pydantic models mirroring the schema from the design doc. A `WorkflowConverter` class takes a `SessionHistory` + metadata and produces a `Workflow` model. The existing `/export-workflow` command is updated to call `get_session_history`, convert to `Workflow`, serialize to JSON, and write to `workflows/<name>.json`.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest

---

### Task 1: Workflow Pydantic Models

**Files:**
- Create: `src/browser_scout/workflow.py`
- Test: `tests/test_workflow.py`

**Step 1: Write the failing tests for workflow models**

```python
"""Tests for workflow JSON schema models."""

from browser_scout.workflow import (
    Workflow,
    WorkflowSettings,
    WorkflowStep,
    WorkflowVariable,
)


def test_workflow_variable_credential():
    var = WorkflowVariable(type="credential", default="your_password", description="Login password")
    assert var.type == "credential"
    assert var.default == "your_password"


def test_workflow_variable_defaults():
    var = WorkflowVariable()
    assert var.type == "string"
    assert var.default == ""
    assert var.description == ""


def test_workflow_settings_defaults():
    settings = WorkflowSettings()
    assert settings.headless is False
    assert settings.default_timeout_ms == 30000
    assert settings.step_delay_ms == 500
    assert settings.on_error == "stop"


def test_workflow_step_navigate():
    step = WorkflowStep(order=1, name="Go to login", action="navigate", value="https://example.com")
    assert step.order == 1
    assert step.action == "navigate"
    assert step.value == "https://example.com"
    assert step.selector is None
    assert step.frame_context is None


def test_workflow_step_click_with_iframe():
    step = WorkflowStep(
        order=5,
        name="Click export button",
        action="click",
        selector="#exportBtn",
        frame_context="iframe#adprIframe",
    )
    assert step.frame_context == "iframe#adprIframe"


def test_workflow_step_type_with_variable_ref():
    step = WorkflowStep(
        order=2,
        name="Enter username",
        action="type",
        selector="#username",
        value="${USERNAME}",
        clear_first=True,
    )
    assert step.value == "${USERNAME}"
    assert step.clear_first is True


def test_workflow_step_wait_for_download():
    step = WorkflowStep(
        order=9,
        name="Wait for CSV download",
        action="wait_for_download",
        timeout_ms=60000,
        filename_pattern="*.csv",
    )
    assert step.action == "wait_for_download"
    assert step.filename_pattern == "*.csv"


def test_workflow_step_wait_for_response():
    step = WorkflowStep(
        order=7,
        name="Wait for report API response",
        action="wait_for_response",
        url_pattern=r"/api/reports/\d+",
        timeout_ms=15000,
    )
    assert step.action == "wait_for_response"
    assert step.url_pattern == r"/api/reports/\d+"


def test_workflow_step_defaults():
    step = WorkflowStep(order=1, name="test", action="click", selector="#btn")
    assert step.on_error is None
    assert step.timeout_ms is None
    assert step.clear_first is None
    assert step.shadow_pierce is None
    assert step.wait_for_load is None
    assert step.filename_pattern is None
    assert step.url_pattern is None
    assert step.method is None
    assert step.download_dir is None


def test_full_workflow():
    workflow = Workflow(
        name="test-workflow",
        description="A test workflow",
        variables={
            "USERNAME": WorkflowVariable(type="credential", default="your_user"),
        },
        steps=[
            WorkflowStep(order=1, name="Navigate", action="navigate", value="https://example.com"),
            WorkflowStep(order=2, name="Type user", action="type", selector="#user", value="${USERNAME}"),
        ],
    )
    assert workflow.schema_version == "1.0"
    assert workflow.name == "test-workflow"
    assert len(workflow.steps) == 2
    assert "USERNAME" in workflow.variables


def test_workflow_to_json_roundtrip():
    workflow = Workflow(
        name="roundtrip-test",
        description="Tests JSON serialization roundtrip",
        steps=[
            WorkflowStep(order=1, name="Navigate", action="navigate", value="https://example.com"),
        ],
    )
    json_str = workflow.model_dump_json(exclude_none=True, indent=2)
    restored = Workflow.model_validate_json(json_str)
    assert restored.name == "roundtrip-test"
    assert restored.steps[0].value == "https://example.com"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_workflow.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'browser_scout.workflow'`

**Step 3: Write the workflow models**

```python
"""Workflow JSON schema models — portable, replayable browser automation recipes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class WorkflowVariable(BaseModel):
    """A declared variable for parameterizing workflow steps."""

    type: Literal["credential", "string", "url"] = "string"
    default: str = ""
    description: str = ""


class WorkflowSettings(BaseModel):
    """Global execution settings for a workflow."""

    headless: bool = False
    default_timeout_ms: int = 30000
    step_delay_ms: int = 500
    on_error: Literal["stop", "continue", "retry"] = "stop"


class WorkflowStep(BaseModel):
    """A single step in a workflow sequence."""

    order: int
    name: str
    action: Literal[
        "navigate", "click", "type", "select", "scroll", "wait",
        "wait_for_download", "wait_for_response",
        "press_key", "hover", "clear",
    ]

    # Common optional fields
    selector: str | None = None
    value: str | None = None
    frame_context: str | None = None
    on_error: Literal["stop", "continue", "retry"] | None = None
    timeout_ms: int | None = None

    # Action-specific optional fields
    shadow_pierce: bool | None = None          # click, type, select
    clear_first: bool | None = None            # type
    wait_for_load: bool | None = None          # navigate
    filename_pattern: str | None = None        # wait_for_download
    download_dir: str | None = None            # wait_for_download
    url_pattern: str | None = None             # wait_for_response
    method: str | None = None                  # wait_for_response


class WorkflowSource(BaseModel):
    """Provenance of a workflow — which tool generated it."""

    tool: str = "browser-scout"
    session_id: str = ""


class Workflow(BaseModel):
    """A portable, replayable browser automation workflow."""

    schema_version: str = "1.0"
    name: str
    description: str = ""
    created: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: WorkflowSource = Field(default_factory=WorkflowSource)
    variables: dict[str, WorkflowVariable] = Field(default_factory=dict)
    settings: WorkflowSettings = Field(default_factory=WorkflowSettings)
    steps: list[WorkflowStep] = Field(default_factory=list)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_workflow.py -v`
Expected: All 11 tests PASS

**Step 5: Commit**

```bash
git add src/browser_scout/workflow.py tests/test_workflow.py
git commit -m "feat: add workflow JSON schema Pydantic models"
```

---

### Task 2: WorkflowConverter — SessionHistory to Workflow

**Files:**
- Modify: `src/browser_scout/workflow.py` (add converter class)
- Test: `tests/test_workflow.py` (add converter tests)

**Step 1: Write the failing tests for the converter**

Add to `tests/test_workflow.py`:

```python
from browser_scout.models import ActionRecord, SessionHistory
from browser_scout.workflow import Workflow, WorkflowConverter


def _make_history(actions: list[ActionRecord], session_id: str = "test-session") -> SessionHistory:
    """Helper to build a minimal SessionHistory for testing."""
    return SessionHistory(
        session_id=session_id,
        started_at="2026-02-19T14:00:00Z",
        actions=actions,
    )


def test_converter_navigate_action():
    history = _make_history([
        ActionRecord(action="navigate", value="https://example.com", success=True, timestamp="2026-02-19T14:00:01Z"),
    ])
    workflow = WorkflowConverter.from_history(history, name="test")
    assert len(workflow.steps) == 1
    assert workflow.steps[0].action == "navigate"
    assert workflow.steps[0].value == "https://example.com"
    assert workflow.steps[0].order == 1


def test_converter_skips_failed_actions():
    history = _make_history([
        ActionRecord(action="click", selector="#btn", success=True, timestamp="T1"),
        ActionRecord(action="click", selector="#missing", success=False, error="not found", timestamp="T2"),
        ActionRecord(action="type", selector="#input", value="hello", success=True, timestamp="T3"),
    ])
    workflow = WorkflowConverter.from_history(history, name="test")
    assert len(workflow.steps) == 2
    assert workflow.steps[0].action == "click"
    assert workflow.steps[1].action == "type"
    assert workflow.steps[1].order == 2


def test_converter_preserves_frame_context():
    history = _make_history([
        ActionRecord(
            action="click", selector="#btn", frame_context="iframe#content",
            success=True, timestamp="T1",
        ),
    ])
    workflow = WorkflowConverter.from_history(history, name="test")
    assert workflow.steps[0].frame_context == "iframe#content"


def test_converter_strips_main_frame_context():
    history = _make_history([
        ActionRecord(
            action="click", selector="#btn", frame_context="main",
            success=True, timestamp="T1",
        ),
    ])
    workflow = WorkflowConverter.from_history(history, name="test")
    assert workflow.steps[0].frame_context is None


def test_converter_parameterizes_password():
    history = _make_history([
        ActionRecord(action="type", selector="#login-form_password", value="s3cret!", success=True, timestamp="T1"),
    ])
    workflow = WorkflowConverter.from_history(history, name="test")
    assert workflow.steps[0].value == "${PASSWORD}"
    assert "PASSWORD" in workflow.variables
    assert workflow.variables["PASSWORD"].type == "credential"


def test_converter_parameterizes_username_before_password():
    history = _make_history([
        ActionRecord(action="type", selector="#login-form_username", value="admin", success=True, timestamp="T1"),
        ActionRecord(action="click", selector="#next", success=True, timestamp="T2"),
        ActionRecord(action="type", selector="#login-form_password", value="s3cret!", success=True, timestamp="T3"),
    ])
    workflow = WorkflowConverter.from_history(history, name="test")
    assert workflow.steps[0].value == "${USERNAME}"
    assert "USERNAME" in workflow.variables
    assert workflow.variables["USERNAME"].type == "credential"
    # Step 2 (click) is preserved between username and password
    assert workflow.steps[2].value == "${PASSWORD}"


def test_converter_auto_generates_step_names():
    history = _make_history([
        ActionRecord(action="navigate", value="https://example.com/login", success=True, timestamp="T1"),
        ActionRecord(action="click", selector="#submit-btn", success=True, timestamp="T2"),
    ])
    workflow = WorkflowConverter.from_history(history, name="test")
    assert "Navigate" in workflow.steps[0].name or "navigate" in workflow.steps[0].name.lower()
    assert workflow.steps[1].name  # Non-empty name generated


def test_converter_sets_source():
    history = _make_history([], session_id="sess-abc")
    workflow = WorkflowConverter.from_history(history, name="test")
    assert workflow.source.tool == "browser-scout"
    assert workflow.source.session_id == "sess-abc"


def test_converter_json_output_excludes_none():
    history = _make_history([
        ActionRecord(action="click", selector="#btn", success=True, timestamp="T1"),
    ])
    workflow = WorkflowConverter.from_history(history, name="test")
    json_str = workflow.model_dump_json(exclude_none=True, indent=2)
    # None fields like frame_context, shadow_pierce should not appear
    assert "frame_context" not in json_str
    assert "shadow_pierce" not in json_str
    assert "url_pattern" not in json_str
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_workflow.py -v -k converter`
Expected: FAIL — `ImportError: cannot import name 'WorkflowConverter'`

**Step 3: Write the converter**

Add to `src/browser_scout/workflow.py`:

```python
import re

from .models import ActionRecord, SessionHistory


# Patterns that indicate a credential field
_PASSWORD_PATTERNS = re.compile(r"password|passwd|pwd|secret", re.IGNORECASE)
_USERNAME_PATTERNS = re.compile(r"username|user|email|login|userid", re.IGNORECASE)


class WorkflowConverter:
    """Converts a browser-scout SessionHistory into a portable Workflow."""

    @staticmethod
    def from_history(
        history: SessionHistory,
        name: str,
        description: str = "",
    ) -> Workflow:
        """Build a Workflow from a SessionHistory.

        - Filters to successful actions only
        - Auto-generates human-readable step names
        - Parameterizes credential fields (password/username)
        - Strips 'main' frame_context (it's the default)
        """
        successful = [a for a in history.actions if a.success]

        # First pass: identify credential fields
        password_indices: set[int] = set()
        username_indices: set[int] = set()

        for i, action in enumerate(successful):
            if action.action == "type" and action.selector:
                if _PASSWORD_PATTERNS.search(action.selector):
                    password_indices.add(i)
                    # Look backward for the nearest type action on a username-like field
                    for j in range(i - 1, -1, -1):
                        prev = successful[j]
                        if prev.action == "type" and prev.selector and _USERNAME_PATTERNS.search(prev.selector):
                            username_indices.add(j)
                            break

        # Build variables
        variables: dict[str, WorkflowVariable] = {}
        if password_indices:
            variables["PASSWORD"] = WorkflowVariable(
                type="credential", default="your_password", description="Login password",
            )
        if username_indices:
            variables["USERNAME"] = WorkflowVariable(
                type="credential", default="your_username", description="Login username",
            )

        # Second pass: build steps
        steps: list[WorkflowStep] = []
        for i, action in enumerate(successful):
            value = action.value
            if i in password_indices:
                value = "${PASSWORD}"
            elif i in username_indices:
                value = "${USERNAME}"

            frame_context = action.frame_context
            if frame_context == "main":
                frame_context = None

            step = WorkflowStep(
                order=len(steps) + 1,
                name=_generate_step_name(action),
                action=action.action,
                selector=action.selector,
                value=value,
                frame_context=frame_context if frame_context else None,
            )
            steps.append(step)

        return Workflow(
            name=name,
            description=description,
            source=WorkflowSource(tool="browser-scout", session_id=history.session_id),
            variables=variables,
            steps=steps,
        )


def _generate_step_name(action: ActionRecord) -> str:
    """Generate a human-readable name for a workflow step."""
    match action.action:
        case "navigate":
            # Extract domain from URL for readability
            url = action.value or ""
            try:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc
                return f"Navigate to {domain}" if domain else "Navigate"
            except Exception:
                return "Navigate"
        case "click":
            selector = action.selector or ""
            return f"Click '{selector}'"
        case "type":
            selector = action.selector or ""
            return f"Type into '{selector}'"
        case "select":
            selector = action.selector or ""
            return f"Select option in '{selector}'"
        case "scroll":
            return f"Scroll page"
        case "wait":
            if action.selector:
                return f"Wait for '{action.selector}'"
            return f"Wait {action.value or '1000'}ms"
        case "press_key":
            return f"Press '{action.value}' key"
        case "hover":
            return f"Hover over '{action.selector}'"
        case "clear":
            return f"Clear '{action.selector}'"
        case _:
            return action.action.replace("_", " ").title()
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_workflow.py -v`
Expected: All tests PASS (both model and converter tests)

**Step 5: Commit**

```bash
git add src/browser_scout/workflow.py tests/test_workflow.py
git commit -m "feat: add WorkflowConverter to transform session history into workflow JSON"
```

---

### Task 3: Update /export-workflow to Output JSON

**Files:**
- Modify: `commands/export-workflow.md`

**Step 1: Read the current export-workflow command**

File is at `commands/export-workflow.md`. Already read above.

**Step 2: Update the command to add JSON output**

Add a new section after Step 5 (before Step 6) in the command that generates JSON output using the `WorkflowConverter`. The command should:

1. After getting session history, import and call `WorkflowConverter.from_history()`
2. Serialize with `workflow.model_dump_json(exclude_none=True, indent=2)`
3. Write to `workflows/<name>.json` alongside the `.py` script
4. Present both files to the user

Update `commands/export-workflow.md` by adding after the existing Step 5 section:

```markdown
## Step 5b: Generate workflow JSON

In addition to the Python script, generate a workflow JSON file using the schema from `src/browser_scout/workflow.py`:

1. Build a `Workflow` model from the session history using `WorkflowConverter.from_history()`
2. Pass the workflow name and a description derived from the key actions
3. Serialize with `model_dump_json(exclude_none=True, indent=2)`
4. The JSON file will be written alongside the Python script

The JSON format is the portable, machine-parseable representation. It uses the same credential parameterization and step ordering as the Python script, but can be consumed by any executor (Python, C#, etc.).
```

Also update Step 7 to write both files:

```markdown
## Step 7: Write the files

Write the Python script to `workflows/<workflow-name>.py` and the workflow JSON to `workflows/<workflow-name>.json` in the current project directory. Create the `workflows/` directory if it doesn't exist.

Present both files to the user and tell them:
- The file paths where they were saved
- How to run the Python script: `python workflows/<name>.py`
- That the JSON file is the portable workflow definition for use with any executor
- What they need to update (credentials, BASE_URL if different environment)
- That botasaurus-driver must be installed: `pip install botasaurus-driver`
```

**Step 3: Commit**

```bash
git add commands/export-workflow.md
git commit -m "feat: update /export-workflow to output JSON alongside Python scripts"
```

---

### Task 4: Validation — Verify Workflow JSON Schema Matches Design Doc

**Files:**
- Test: `tests/test_workflow.py` (add schema validation tests)

**Step 1: Write schema validation tests**

Add to `tests/test_workflow.py`:

```python
import json


def test_workflow_json_schema_has_required_envelope_fields():
    """Verify the JSON schema matches the design doc envelope."""
    workflow = Workflow(name="schema-test", description="Testing schema compliance")
    data = json.loads(workflow.model_dump_json(exclude_none=True))

    assert "schema_version" in data
    assert "name" in data
    assert "description" in data
    assert "created" in data
    assert "source" in data
    assert "variables" in data
    assert "settings" in data
    assert "steps" in data


def test_workflow_json_schema_all_action_types_valid():
    """Every action type from the design doc can be instantiated."""
    action_configs = [
        {"action": "navigate", "value": "https://example.com"},
        {"action": "click", "selector": "#btn"},
        {"action": "type", "selector": "#input", "value": "hello"},
        {"action": "select", "selector": "#dropdown", "value": "option1"},
        {"action": "scroll", "value": "500"},
        {"action": "wait", "value": "2000"},
        {"action": "wait_for_download", "filename_pattern": "*.csv"},
        {"action": "wait_for_response", "url_pattern": "/api/data"},
        {"action": "press_key", "value": "Enter"},
        {"action": "hover", "selector": "#menu"},
        {"action": "clear", "selector": "#input"},
    ]
    for i, config in enumerate(action_configs):
        step = WorkflowStep(order=i + 1, name=f"Step {i + 1}", **config)
        assert step.action == config["action"]


def test_full_adp_workflow_from_design_doc():
    """Instantiate the complete ADP example from the design doc."""
    from browser_scout.workflow import WorkflowSource, WorkflowVariable

    workflow = Workflow(
        name="adp-report-download",
        description="Log into ADP WFN and download the Unum LTD FMLA report",
        source=WorkflowSource(tool="browser-scout", session_id="abc123"),
        variables={
            "USERNAME": WorkflowVariable(type="credential", default="your_username"),
            "PASSWORD": WorkflowVariable(type="credential", default="your_password"),
            "REPORT_NAME": WorkflowVariable(type="string", default="Unum_LTD_FMLA_Report"),
        },
        settings=WorkflowSettings(headless=False, default_timeout_ms=30000, step_delay_ms=500, on_error="stop"),
        steps=[
            WorkflowStep(order=1, name="Navigate to ADP sign-in", action="navigate",
                         value="https://online.adp.com/signin/v1/?APPID=WFNPortal"),
            WorkflowStep(order=2, name="Enter username", action="type",
                         selector="#login-form_username", value="${USERNAME}", clear_first=True),
            WorkflowStep(order=3, name="Click Next button", action="click",
                         selector="[data-testid='verifUseridBtn']"),
            WorkflowStep(order=4, name="Enter password", action="type",
                         selector="#login-form_password", value="${PASSWORD}", clear_first=True),
            WorkflowStep(order=5, name="Click Sign In", action="click", selector="#signBtn"),
            WorkflowStep(order=6, name="Wait for WFN dashboard", action="wait",
                         selector="#shellNavComponent", timeout_ms=15000),
            WorkflowStep(order=7, name="Navigate to Custom Reports", action="navigate",
                         value="https://workforcenow.adp.com/theme/admin.html#/Reports/ReportsTabCustomReportsCategoryAllReports"),
            WorkflowStep(order=8, name="Click report link", action="click",
                         selector="[aria-label='${REPORT_NAME}']",
                         frame_context="iframe#adprIframe", timeout_ms=15000),
            WorkflowStep(order=9, name="Wait for report download", action="wait_for_download",
                         timeout_ms=60000, filename_pattern="*.csv"),
        ],
    )

    # Roundtrip through JSON
    json_str = workflow.model_dump_json(exclude_none=True, indent=2)
    restored = Workflow.model_validate_json(json_str)

    assert restored.name == "adp-report-download"
    assert len(restored.steps) == 9
    assert restored.variables["USERNAME"].type == "credential"
    assert restored.steps[7].frame_context == "iframe#adprIframe"
    assert restored.steps[8].action == "wait_for_download"
```

**Step 2: Run all tests**

Run: `pytest tests/test_workflow.py -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add tests/test_workflow.py
git commit -m "test: add schema validation tests for workflow JSON"
```

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | Pydantic models for Workflow, WorkflowStep, WorkflowVariable, WorkflowSettings | `workflow.py`, `test_workflow.py` |
| 2 | WorkflowConverter: SessionHistory → Workflow (credential parameterization, step naming) | `workflow.py`, `test_workflow.py` |
| 3 | Update `/export-workflow` command to output JSON alongside Python | `export-workflow.md` |
| 4 | Schema validation tests (envelope fields, all action types, full ADP example roundtrip) | `test_workflow.py` |
