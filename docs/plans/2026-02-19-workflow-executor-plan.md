# Workflow Executor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a standalone CLI tool (`workflow-run`) that reads workflow JSON files and replays them via botasaurus-driver, with JSON structured output, variable resolution, and failure screenshots.

**Architecture:** Single new module `src/browser_scout/executor.py` containing a `WorkflowExecutor` class (core logic) and a `main()` CLI entry point. Reuses existing `NetworkMonitor` from `network.py` for download/response waits, and mirrors `actions.py`'s iframe resolution and action dispatch patterns.

**Tech Stack:** Python 3.11+, Pydantic v2, botasaurus-driver, argparse, pytest

**Spec:** `docs/specs/2026-02-19-workflow-executor.md`

---

## Problem Statement

Browser-scout generates workflow JSON files but has no way to replay them without Claude. A standalone executor enables scheduled automation, CI integration, and workflow testing.

## Constraints

- Must work with existing workflow JSON schema (no schema changes)
- Must reuse `NetworkMonitor` from `network.py` (not reimplement download detection)
- Must be synchronous (botasaurus-driver is sync)
- No new pip dependencies beyond what's already in `pyproject.toml`
- `retry` error policy is parsed but treated as `stop` in V1

## Approach

Build the executor as 4 independently testable layers:

1. **Variable resolver** — resolves `${VAR}` references from CLI args → env → defaults
2. **Step dispatcher** — maps `WorkflowStep.action` to botasaurus-driver calls
3. **Execution loop** — orchestrates steps with look-ahead, error handling, timing
4. **CLI entry point** — argparse wrapper, dry-run mode, JSON output

Each layer is unit-testable without a browser. Integration tests (with browser) are a separate task at the end.

## Impact Analysis

| Action | File | Description |
|--------|------|-------------|
| Create | `src/browser_scout/executor.py` | Core executor + CLI (~300 lines) |
| Create | `tests/test_executor.py` | Unit tests (~250 lines) |
| Modify | `pyproject.toml` | Add `workflow-run` script entry point |

Total: 2 new files, 1 modified file. No changes to existing browser-scout functionality.

## Sequence

---

### Task 1: Variable Resolver

**Files:**
- Create: `src/browser_scout/executor.py` (initial file with resolver only)
- Create: `tests/test_executor.py`

**Step 1: Write failing tests for variable resolution**

```python
"""Tests for the workflow executor."""

import json
import os
from unittest.mock import patch

import pytest

from browser_scout.executor import resolve_variables
from browser_scout.workflow import Workflow, WorkflowSettings, WorkflowStep, WorkflowVariable


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
            "PATH": WorkflowVariable(type="string", default="/reports"),
        },
        steps=[WorkflowStep(order=1, name="Nav", action="navigate", value="https://${HOST}${PATH}")],
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
```

**Step 2: Run tests — expect failure (module not found)**

Run: `d:/Projects/browser-scout/.venv/Scripts/python -m pytest tests/test_executor.py -v`

**Step 3: Implement the variable resolver**

Create `src/browser_scout/executor.py`:

```python
"""Workflow executor — replays workflow JSON files via botasaurus-driver."""

from __future__ import annotations

import os
import re
import sys

from .workflow import Workflow, WorkflowStep


_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


def resolve_variables(workflow: Workflow, cli_vars: dict[str, str]) -> Workflow:
    """Resolve all ${VAR} references in a workflow's steps.

    Resolution order: cli_vars → environment variables → workflow variable defaults.
    Returns a new Workflow with all references resolved.
    Exits with code 2 if any variable cannot be resolved.
    """
    # Build the resolution map
    resolved_values: dict[str, str] = {}
    unresolved: list[str] = []

    for var_name, var_def in workflow.variables.items():
        if var_name in cli_vars:
            resolved_values[var_name] = cli_vars[var_name]
        elif var_name in os.environ:
            resolved_values[var_name] = os.environ[var_name]
        elif var_def.default and var_def.default not in ("your_username", "your_password"):
            resolved_values[var_name] = var_def.default
        else:
            unresolved.append(var_name)

    if unresolved:
        print(
            f'{{"error": "unresolved_variables", "variables": {unresolved}}}',
            file=sys.stderr,
        )
        sys.exit(2)

    # Resolve references in all step string fields
    resolved_steps = []
    for step in workflow.steps:
        resolved_steps.append(_resolve_step(step, resolved_values))

    return workflow.model_copy(update={"steps": resolved_steps})


def _resolve_step(step: WorkflowStep, values: dict[str, str]) -> WorkflowStep:
    """Resolve ${VAR} references in a step's string fields."""
    updates: dict[str, str] = {}

    for field_name in ("selector", "value", "url_pattern"):
        field_val = getattr(step, field_name)
        if field_val and "${" in field_val:
            resolved = _VAR_PATTERN.sub(
                lambda m: values.get(m.group(1), m.group(0)),
                field_val,
            )
            updates[field_name] = resolved

    if updates:
        return step.model_copy(update=updates)
    return step
```

**Step 4: Run tests — expect all pass**

Run: `d:/Projects/browser-scout/.venv/Scripts/python -m pytest tests/test_executor.py -v`

**Step 5: Commit**

```bash
git add src/browser_scout/executor.py tests/test_executor.py
git commit -m "feat: add variable resolver for workflow executor"
```

---

### Task 2: Step Dispatcher

**Files:**
- Modify: `src/browser_scout/executor.py` (add step dispatch)
- Modify: `tests/test_executor.py` (add dispatch tests)

The step dispatcher is a function that takes a botasaurus `Driver`, a `WorkflowStep`, and the workflow settings, then executes the appropriate browser action. It mirrors `actions.py` but consumes `WorkflowStep` fields instead of raw parameters.

**Step 1: Write failing tests for step dispatch**

Append to `tests/test_executor.py`:

```python
from browser_scout.executor import resolve_error_policy


# --- Error policy tests ---


def test_error_policy_step_overrides_global():
    assert resolve_error_policy(step_policy="continue", global_policy="stop") == "continue"


def test_error_policy_falls_back_to_global():
    assert resolve_error_policy(step_policy=None, global_policy="continue") == "continue"


def test_error_policy_retry_treated_as_stop():
    assert resolve_error_policy(step_policy="retry", global_policy="continue") == "stop"


def test_error_policy_global_retry_treated_as_stop():
    assert resolve_error_policy(step_policy=None, global_policy="retry") == "stop"
```

**Step 2: Run tests — expect failure (import error)**

**Step 3: Implement error policy resolution**

Add to `src/browser_scout/executor.py`:

```python
def resolve_error_policy(
    step_policy: str | None,
    global_policy: str,
) -> str:
    """Resolve the effective error policy for a step.

    Step-level overrides global. 'retry' is treated as 'stop' in V1.
    """
    policy = step_policy if step_policy is not None else global_policy
    if policy == "retry":
        return "stop"
    return policy
```

**Step 4: Run tests — expect pass**

**Step 5: Commit**

```bash
git add src/browser_scout/executor.py tests/test_executor.py
git commit -m "feat: add error policy resolution for workflow executor"
```

---

### Task 3: Execution Loop + CLI

**Files:**
- Modify: `src/browser_scout/executor.py` (add WorkflowExecutor class + main())
- Modify: `tests/test_executor.py` (add look-ahead and dry-run tests)

This is the largest task. It ties the resolver and dispatcher together into the execution loop, adds the look-ahead logic for network monitoring, and provides the CLI entry point.

**Step 1: Write failing tests for look-ahead and dry-run**

Append to `tests/test_executor.py`:

```python
from browser_scout.executor import needs_pre_monitoring, mask_credential_value
from browser_scout.workflow import WorkflowVariable


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
```

**Step 2: Run tests — expect failure**

**Step 3: Implement the execution loop and CLI**

Add to `src/browser_scout/executor.py`:

```python
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from botasaurus_driver import Driver

from .network import NetworkMonitor
from .workflow import Workflow, WorkflowStep, WorkflowVariable


def needs_pre_monitoring(next_step: WorkflowStep | None) -> bool:
    """Check if the next step requires network monitoring to be started."""
    if next_step is None:
        return False
    return next_step.action in ("wait_for_download", "wait_for_response")


def mask_credential_value(
    original_ref: str,
    resolved_value: str,
    variables: dict[str, WorkflowVariable],
) -> str:
    """Mask credential values for log output."""
    match = _VAR_PATTERN.search(original_ref)
    if match:
        var_name = match.group(1)
        var_def = variables.get(var_name)
        if var_def and var_def.type == "credential":
            return "****"
    return resolved_value


def _resolve_target(driver: Driver, frame_context: str | None):
    """Resolve iframe context. Returns driver or iframe handle."""
    if not frame_context:
        return driver

    # Support nested iframes via >>> syntax
    parts = [p.strip() for p in frame_context.split(">>>")]
    target = driver
    for part in parts:
        iframe = target.select_iframe(part)
        if iframe is None:
            raise ValueError(f"Iframe not found: {part}")
        target = iframe
    return target


class WorkflowExecutor:
    """Executes a resolved workflow via botasaurus-driver."""

    def __init__(
        self,
        workflow: Workflow,
        headless: bool | None = None,
        download_dir: str = "./downloads",
        screenshot_dir: str = "./screenshots",
    ) -> None:
        self.workflow = workflow
        self.headless = headless if headless is not None else workflow.settings.headless
        self.download_dir = os.path.abspath(download_dir)
        self.screenshot_dir = os.path.abspath(screenshot_dir)
        self.driver: Driver | None = None
        self.monitor: NetworkMonitor | None = None
        self.passed = 0
        self.failed = 0

    def run(self) -> int:
        """Execute all steps. Returns exit code (0=success, 1=failure)."""
        os.makedirs(self.download_dir, exist_ok=True)
        start_time = time.perf_counter()

        try:
            self.driver = Driver(headless=self.headless)
            self.monitor = NetworkMonitor(self.download_dir)

            steps = self.workflow.steps
            default_timeout = self.workflow.settings.default_timeout_ms
            step_delay = self.workflow.settings.step_delay_ms
            global_policy = self.workflow.settings.on_error

            for i, step in enumerate(steps):
                next_step = steps[i + 1] if i + 1 < len(steps) else None

                # Look-ahead: start monitoring if next step needs it
                if needs_pre_monitoring(next_step):
                    self.monitor.start(self.driver, url_pattern=next_step.url_pattern)

                result = self._execute_step(step, default_timeout)

                if result["status"] == "ok":
                    self.passed += 1
                else:
                    self.failed += 1
                    policy = resolve_error_policy(step.on_error, global_policy)
                    if policy == "stop":
                        break

                # Step delay
                if step_delay > 0 and i < len(steps) - 1:
                    time.sleep(step_delay / 1000)

        finally:
            if self.monitor:
                self.monitor.stop()
            if self.driver:
                try:
                    self.driver.close()
                except Exception:
                    pass

        total_ms = int((time.perf_counter() - start_time) * 1000)
        status = "ok" if self.failed == 0 else "failed"
        summary = {
            "summary": True,
            "total_steps": len(self.workflow.steps),
            "passed": self.passed,
            "failed": self.failed,
            "elapsed_ms": total_ms,
            "status": status,
        }
        print(json.dumps(summary))

        return 0 if self.failed == 0 else 1

    def _execute_step(self, step: WorkflowStep, default_timeout: int) -> dict:
        """Execute a single step and emit a JSON log line."""
        start = time.perf_counter()
        error = None

        try:
            target = _resolve_target(self.driver, step.frame_context)
            timeout_s = (step.timeout_ms or default_timeout) / 1000

            match step.action:
                case "navigate":
                    self.driver.get(step.value)

                case "click":
                    target.click(step.selector)

                case "type":
                    if step.clear_first:
                        target.clear(step.selector)
                    target.type(step.selector, step.value)

                case "select":
                    if step.value and step.value.isdigit():
                        target.select_option(step.selector, index=int(step.value))
                    else:
                        target.select_option(step.selector, value=step.value)

                case "scroll":
                    amount = int(step.value) if step.value else 500
                    self.driver.run_js(f"window.scrollBy(0, {amount})")

                case "wait":
                    if step.selector:
                        target.wait_for_element(step.selector, wait=timeout_s)
                    elif step.value:
                        time.sleep(int(step.value) / 1000)
                    else:
                        time.sleep(1)

                case "wait_for_download":
                    timeout = step.timeout_ms or default_timeout
                    download_events = self.monitor.wait_for_download(timeout)
                    self.monitor.stop()
                    if download_events:
                        elapsed = int((time.perf_counter() - start) * 1000)
                        result = {
                            "step": step.order, "name": step.name,
                            "action": step.action, "status": "ok",
                            "elapsed_ms": elapsed,
                            "file": download_events[0].download_filename,
                        }
                        print(json.dumps(result))
                        return result

                case "wait_for_response":
                    timeout = step.timeout_ms or default_timeout
                    deadline = time.perf_counter() + timeout / 1000
                    matched = []
                    while time.perf_counter() < deadline:
                        matched = self.monitor.query(step.url_pattern)
                        if matched:
                            break
                        time.sleep(0.5)
                    self.monitor.stop()

                case "press_key":
                    from botasaurus_driver import cdp
                    key_map = _get_key_map()
                    key_info = key_map.get(
                        step.value.lower(),
                        {"key": step.value, "code": f"Key{step.value.upper()}"},
                    )
                    self.driver.run_cdp_command(cdp.input_.dispatch_key_event(
                        type_="keyDown", key=key_info["key"],
                        code=key_info["code"],
                        windows_virtual_key_code=key_info.get("keyCode", 0),
                    ))
                    self.driver.run_cdp_command(cdp.input_.dispatch_key_event(
                        type_="keyUp", key=key_info["key"],
                        code=key_info["code"],
                        windows_virtual_key_code=key_info.get("keyCode", 0),
                    ))

                case "hover":
                    import json as json_mod
                    sel_js = json_mod.dumps(step.selector)
                    hover_js = (
                        "const el = document.querySelector(" + sel_js + ");"
                        "if (!el) return null;"
                        "const rect = el.getBoundingClientRect();"
                        "return {x: rect.x + rect.width/2, y: rect.y + rect.height/2};"
                    )
                    pos = self.driver.run_js(hover_js)
                    if pos:
                        from botasaurus_driver import cdp
                        self.driver.run_cdp_command(cdp.input_.dispatch_mouse_event(
                            type_="mouseMoved", x=pos["x"], y=pos["y"],
                        ))
                    else:
                        raise ValueError(f"Element not found for hover: {step.selector}")

                case "clear":
                    target.clear(step.selector)

                case _:
                    raise ValueError(f"Unknown action: {step.action}")

        except Exception as e:
            error = str(e)

        elapsed = int((time.perf_counter() - start) * 1000)
        result = {
            "step": step.order,
            "name": step.name,
            "action": step.action,
            "status": "ok" if error is None else "error",
            "elapsed_ms": elapsed,
        }
        if error:
            result["error"] = error
            screenshot_path = self._capture_screenshot(step.order)
            if screenshot_path:
                result["screenshot"] = screenshot_path

        print(json.dumps(result))
        return result

    def _capture_screenshot(self, step_order: int) -> str | None:
        """Capture a failure screenshot. Returns the file path or None."""
        if not self.driver:
            return None
        try:
            os.makedirs(self.screenshot_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"step-{step_order}-error-{timestamp}.png"
            filepath = os.path.join(self.screenshot_dir, filename)
            self.driver.save_screenshot(filepath)
            return filepath
        except Exception:
            return None


def _get_key_map() -> dict:
    """Map common key names to CDP key event parameters."""
    return {
        "enter": {"key": "Enter", "code": "Enter", "keyCode": 13},
        "tab": {"key": "Tab", "code": "Tab", "keyCode": 9},
        "escape": {"key": "Escape", "code": "Escape", "keyCode": 27},
        "space": {"key": " ", "code": "Space", "keyCode": 32},
        "backspace": {"key": "Backspace", "code": "Backspace", "keyCode": 8},
        "delete": {"key": "Delete", "code": "Delete", "keyCode": 46},
        "arrowup": {"key": "ArrowUp", "code": "ArrowUp", "keyCode": 38},
        "arrowdown": {"key": "ArrowDown", "code": "ArrowDown", "keyCode": 40},
        "arrowleft": {"key": "ArrowLeft", "code": "ArrowLeft", "keyCode": 37},
        "arrowright": {"key": "ArrowRight", "code": "ArrowRight", "keyCode": 39},
        "home": {"key": "Home", "code": "Home", "keyCode": 36},
        "end": {"key": "End", "code": "End", "keyCode": 35},
        "pageup": {"key": "PageUp", "code": "PageUp", "keyCode": 33},
        "pagedown": {"key": "PageDown", "code": "PageDown", "keyCode": 34},
    }


def dry_run(workflow: Workflow) -> None:
    """Print the execution plan without running."""
    header = {
        "dry_run": True,
        "name": workflow.name,
        "total_steps": len(workflow.steps),
        "variables_resolved": len(workflow.variables),
    }
    print(json.dumps(header))

    for step in workflow.steps:
        line: dict = {
            "step": step.order,
            "action": step.action,
        }
        if step.selector:
            line["selector"] = step.selector
        if step.value:
            line["value"] = mask_credential_value(
                step.value, step.value, workflow.variables,
            )
        if step.frame_context:
            line["frame_context"] = step.frame_context
        print(json.dumps(line))


def main() -> None:
    """CLI entry point for workflow-run."""
    parser = argparse.ArgumentParser(
        prog="workflow-run",
        description="Execute a browser-scout workflow JSON file",
    )
    parser.add_argument("workflow", help="Path to the workflow JSON file")
    parser.add_argument("--var", action="append", default=[], metavar="KEY=VALUE",
                        help="Set a variable (repeatable)")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--download-dir", default="./downloads", help="Download directory")
    parser.add_argument("--screenshot-dir", default="./screenshots", help="Screenshot directory")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print plan without running")
    parser.add_argument("--timeout", type=int, help="Override default timeout (ms)")

    args = parser.parse_args()

    # Parse --var KEY=VALUE pairs
    cli_vars: dict[str, str] = {}
    for var_str in args.var:
        if "=" not in var_str:
            print(f'{{"error": "invalid_var", "value": "{var_str}", "expected": "KEY=VALUE"}}',
                  file=sys.stderr)
            sys.exit(2)
        key, val = var_str.split("=", 1)
        cli_vars[key] = val

    # Load and validate workflow
    workflow_path = Path(args.workflow)
    if not workflow_path.exists():
        print(f'{{"error": "file_not_found", "path": "{args.workflow}"}}', file=sys.stderr)
        sys.exit(2)

    try:
        workflow = Workflow.model_validate_json(workflow_path.read_text())
    except Exception as e:
        print(f'{{"error": "invalid_workflow", "detail": "{e}"}}', file=sys.stderr)
        sys.exit(2)

    # Apply CLI overrides to settings
    if args.timeout:
        workflow = workflow.model_copy(
            update={"settings": workflow.settings.model_copy(update={"default_timeout_ms": args.timeout})}
        )

    # Resolve variables
    resolved = resolve_variables(workflow, cli_vars)

    # Dry run mode
    if args.dry_run:
        dry_run(resolved)
        sys.exit(0)

    # Execute
    executor = WorkflowExecutor(
        workflow=resolved,
        headless=args.headless or None,
        download_dir=args.download_dir,
        screenshot_dir=args.screenshot_dir,
    )
    exit_code = executor.run()
    sys.exit(exit_code)
```

**Step 4: Run tests — expect all pass**

Run: `d:/Projects/browser-scout/.venv/Scripts/python -m pytest tests/test_executor.py -v`

**Step 5: Commit**

```bash
git add src/browser_scout/executor.py tests/test_executor.py
git commit -m "feat: add WorkflowExecutor with execution loop and CLI entry point"
```

---

### Task 4: pyproject.toml Entry Point + Dry-Run Tests

**Files:**
- Modify: `pyproject.toml` (add script entry point)
- Modify: `tests/test_executor.py` (add dry-run and CLI integration tests)

**Step 1: Add entry point to pyproject.toml**

Add to the `[project.scripts]` section:

```toml
workflow-run = "browser_scout.executor:main"
```

**Step 2: Write dry-run integration test**

Append to `tests/test_executor.py`:

```python
import subprocess


def test_dry_run_valid_workflow(tmp_path):
    """Test --dry-run with a valid workflow JSON file."""
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


def test_dry_run_invalid_workflow(tmp_path):
    """Test --dry-run with invalid JSON."""
    workflow_file = tmp_path / "bad.json"
    workflow_file.write_text("not json")

    result = subprocess.run(
        [sys.executable, "-m", "browser_scout.executor", str(workflow_file), "--dry-run"],
        capture_output=True, text=True,
    )
    assert result.returncode == 2


def test_dry_run_missing_file():
    """Test --dry-run with nonexistent file."""
    result = subprocess.run(
        [sys.executable, "-m", "browser_scout.executor", "/nonexistent/workflow.json", "--dry-run"],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
```

**Step 3: Add `__main__.py` for `python -m browser_scout.executor` support**

Create `src/browser_scout/__main__.py` is not needed — instead add to the bottom of `executor.py`:

The `main()` function already exists. For `python -m browser_scout.executor` support, the `if __name__ == "__main__": main()` block handles this. But subprocess tests use `-m browser_scout.executor`, which requires either `__main__.py` or invoking via the module. Since `executor.py` already has the guard, invoke as `python -c "from browser_scout.executor import main; main()"` or adjust the subprocess call to use the installed entry point.

Actually, simpler: the subprocess tests should invoke `sys.executable, "-c", "from browser_scout.executor import main; main()"` with the args appended, OR just test the functions directly without subprocess. Let's test the functions directly for unit tests and only use subprocess for one CLI smoke test.

**Step 4: Run all tests**

Run: `d:/Projects/browser-scout/.venv/Scripts/python -m pytest tests/test_executor.py -v`

**Step 5: Reinstall package for entry point**

Run: `cd d:/Projects/browser-scout && pip install -e .`

**Step 6: Verify CLI works**

Run: `workflow-run --help`

**Step 7: Commit**

```bash
git add pyproject.toml src/browser_scout/executor.py tests/test_executor.py
git commit -m "feat: add workflow-run CLI entry point and dry-run tests"
```

---

### Task 5: Full Test Suite Verification

**Step 1: Run all project tests**

Run: `d:/Projects/browser-scout/.venv/Scripts/python -m pytest tests/ -v`

Expected: All tests pass (existing 50 + new executor tests)

**Step 2: Verify no regressions**

Check that existing workflow model tests, scout filter tests, and integration tests still pass.

**Step 3: Final commit (if any fixups needed)**

---

## Verification Strategy

### Unit tests (no browser needed)
- Variable resolution: 8 tests covering CLI args, env vars, defaults, priority, multi-var, unresolved error
- Error policy: 4 tests covering step override, global fallback, retry→stop
- Look-ahead: 4 tests covering download, response, regular step, None
- Credential masking: 3 tests covering credential, non-credential, plain text
- Dry-run CLI: 3 tests covering valid workflow, invalid JSON, missing file

### Manual verification
- `workflow-run --help` shows usage
- `workflow-run --dry-run workflows/test.json` validates and prints plan
- `workflow-run workflows/test.json --var USERNAME=x --var PASSWORD=y` executes (requires a real workflow)

### Definition of done
- All unit tests pass
- `workflow-run --help` works
- `workflow-run --dry-run` correctly validates and prints a workflow
- Full project test suite (50+ existing tests) still passes
- No new pip dependencies added

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| botasaurus-driver API differences between versions | Medium | Pin version in pyproject.toml. Mirror patterns from working `actions.py`. |
| `_get_key_map` duplication with `actions.py` | Low | Accept duplication for V1. Refactor to shared module in V2 if needed. |
| Subprocess tests fragile on Windows | Medium | Use direct function calls for unit tests. Only 1 subprocess test for CLI smoke test. |
| `NetworkMonitor.wait_for_download` may not detect filesystem downloads (only CDP events) | Medium | The monitor detects `content-disposition: attachment` headers. For downloads triggered by JS (window.location redirect), a filesystem polling fallback may be needed in V2. |

## Staff Engineer Self-Review

1. **REFINE: `_get_key_map` is duplicated from `actions.py`.** Both files define the identical key map. This works but creates a maintenance burden. Acceptable for V1 since the key map is static and unlikely to change. Could be extracted to a `keys.py` module in V2.

2. **REFINE: Variable resolution doesn't handle nested `${VAR}` references.** If a variable's default value itself contains `${OTHER_VAR}`, it won't be resolved. The spec explicitly says "Nested references are not supported" (from the design doc), so this is by design, not a gap. But it should be documented in the `--help` output.

3. **NOTE: The `resolve_variables` function uses `sys.exit(2)` for unresolved variables.** This makes it harder to test (requires `pytest.raises(SystemExit)`). A cleaner pattern would be to raise a custom exception and let `main()` handle the exit. However, since the spec says "exit code 2" and the tests already account for this, it's acceptable.

4. **NOTE: The look-ahead pattern assumes `wait_for_download`/`wait_for_response` always follow the triggering action immediately.** If there's an intervening step (e.g., click → wait → wait_for_download), the monitor won't capture the download from the click. The spec's pseudocode shows the same assumption, so this matches intent.

5. **NOTE: Screenshot capture swallows exceptions silently.** If `driver.save_screenshot()` fails (e.g., screenshot dir is read-only), the error is lost. This is acceptable — screenshot failure shouldn't prevent the step result from being reported.

No BLOCKING concerns. The plan can proceed.
