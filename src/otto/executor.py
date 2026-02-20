"""Workflow executor — replays workflow JSON files via botasaurus-driver."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .actions import _get_key_map
from .network import NetworkMonitor
from .workflow import Workflow, WorkflowStep, WorkflowVariable

if TYPE_CHECKING:
    from botasaurus_driver import Driver

_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


def resolve_variables(workflow: Workflow, cli_vars: dict[str, str]) -> Workflow:
    """Resolve all ${VAR} references in a workflow's steps.

    Resolution order: cli_vars > environment variables > workflow variable defaults.
    Returns a new Workflow with all references resolved.
    Exits with code 2 if any variable cannot be resolved.
    """
    resolved_values: dict[str, str] = {}
    unresolved: list[str] = []

    for var_name, var_def in workflow.variables.items():
        if var_name in cli_vars:
            resolved_values[var_name] = cli_vars[var_name]
        elif var_name in os.environ:
            resolved_values[var_name] = os.environ[var_name]
        elif var_def.default:
            resolved_values[var_name] = var_def.default
        else:
            unresolved.append(var_name)

    if unresolved:
        print(
            f'{{"error": "unresolved_variables", "variables": {unresolved}}}',
            file=sys.stderr,
        )
        sys.exit(2)

    resolved_steps = [_resolve_step(step, resolved_values) for step in workflow.steps]
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


def resolve_error_policy(step_policy: str | None, global_policy: str) -> str:
    """Resolve the effective error policy for a step.

    Step-level overrides global. 'retry' is treated as 'stop' in V1.
    """
    policy = step_policy if step_policy is not None else global_policy
    if policy == "retry":
        return "stop"
    return policy


def needs_pre_monitoring(next_step: WorkflowStep | None) -> bool:
    """Check if the next step requires network monitoring to be started beforehand."""
    if next_step is None:
        return False
    return next_step.action in ("wait_for_download", "wait_for_response")


def mask_credential_value(
    original_ref: str,
    resolved_value: str,
    variables: dict[str, WorkflowVariable],
) -> str:
    """Mask credential values for log output. Returns '****' for credential-type vars."""
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
            from botasaurus_driver import Driver as BotDriver

            self.driver = BotDriver(headless=self.headless)
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
                    sel_js = json.dumps(step.selector)
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


def dry_run(resolved: Workflow, original: Workflow) -> None:
    """Print the execution plan without running.

    Uses original (pre-resolution) step values to detect which fields
    came from credential variables, masking those in the output.
    """
    header = {
        "dry_run": True,
        "name": resolved.name,
        "total_steps": len(resolved.steps),
        "variables_resolved": len(resolved.variables),
    }
    print(json.dumps(header))

    for i, step in enumerate(resolved.steps):
        orig_step = original.steps[i] if i < len(original.steps) else step
        line: dict = {
            "step": step.order,
            "action": step.action,
        }
        if step.selector:
            line["selector"] = step.selector
        if step.value:
            line["value"] = mask_credential_value(
                orig_step.value or step.value, step.value, resolved.variables,
            )
        if step.frame_context:
            line["frame_context"] = step.frame_context
        print(json.dumps(line))


def main() -> None:
    """CLI entry point for workflow-run."""
    parser = argparse.ArgumentParser(
        prog="workflow-run",
        description="Execute an Otto workflow JSON file",
    )
    parser.add_argument("workflow", help="Path to the workflow JSON file")
    parser.add_argument(
        "--var", action="append", default=[], metavar="KEY=VALUE",
        help="Set a variable (repeatable). Overrides env vars and defaults.",
    )
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
            print(
                f'{{"error": "invalid_var", "value": "{var_str}", "expected": "KEY=VALUE"}}',
                file=sys.stderr,
            )
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
        dry_run(resolved, original=workflow)
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


if __name__ == "__main__":
    main()
