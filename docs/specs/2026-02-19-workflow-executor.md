# Feature Spec: Workflow Executor (Phase 2)

**Date:** 2026-02-19
**Status:** Draft
**Depends on:** Phase 1 (workflow JSON schema — complete)

## Problem

Browser-scout can generate portable workflow JSON files via `/export-workflow`, but there is no way to replay them without Claude in the loop. A standalone Python executor would enable:

- Scheduled/automated workflow execution (e.g., nightly report downloads)
- CI/CD integration for browser automation tasks
- Workflow testing and validation without an MCP server

## Solution

A CLI tool (`workflow-run`) that reads a workflow JSON file, launches a botasaurus-driver browser, and executes each step sequentially. Reuses browser-scout's existing `NetworkMonitor` for download/network wait handling.

## User Stories

1. **As a developer,** I want to run `workflow-run workflows/adp-report.json --var USERNAME=admin --var PASSWORD=s3cret` and have it execute the workflow end-to-end, logging JSON-structured output for each step.

2. **As a developer,** I want `workflow-run --dry-run workflows/my-workflow.json` to validate the JSON, resolve variables, and print the execution plan without launching a browser.

3. **As a developer,** when a step fails, I want a screenshot saved automatically so I can debug the page state.

4. **As a developer,** I want the executor to stop on first error by default, but allow per-step `on_error: continue` to skip non-critical steps.

## Architecture

### Code Location

Inside the browser-scout package:

- `src/browser_scout/executor.py` — core `WorkflowExecutor` class and CLI entry point
- Entry point in `pyproject.toml`: `workflow-run = "browser_scout.executor:main"`
- Reuses: `workflow.py` (schema models), `network.py` (NetworkMonitor), `actions.py` (iframe resolution pattern)

### Component Design

```
workflow-run CLI
    │
    ├── Load & validate workflow JSON (Pydantic)
    ├── Resolve variables (CLI args → env vars → defaults)
    ├── [--dry-run: print plan and exit]
    │
    ├── Launch Driver (botasaurus-driver)
    ├── For each step:
    │   ├── Look-ahead: start NetworkMonitor if next step is wait_for_*
    │   ├── Resolve frame_context → target (driver or iframe handle)
    │   ├── Execute action on target
    │   ├── Emit JSON log line to stdout
    │   ├── Handle on_error policy (stop/continue)
    │   └── On failure: capture screenshot
    └── Close Driver (always, via try/finally)
```

## CLI Interface

```
workflow-run <workflow.json> [options]

Arguments:
  workflow.json          Path to the workflow JSON file

Options:
  --var KEY=VALUE        Set a variable (repeatable). Overrides env vars and defaults.
  --headless             Override workflow's headless setting to true
  --download-dir PATH    Override download directory (default: ./downloads)
  --screenshot-dir PATH  Directory for failure screenshots (default: ./screenshots)
  --dry-run              Validate and print execution plan without running
  --timeout MS           Override global default_timeout_ms
```

### Exit Codes

- `0` — All steps completed successfully
- `1` — One or more steps failed
- `2` — Invalid workflow JSON or unresolved variables (pre-execution error)

## Variable Resolution

Resolution order (highest priority first):

1. `--var KEY=VALUE` CLI arguments
2. Environment variables matching the variable name
3. `default` value from the workflow JSON's `variables` section
4. **Error** — unresolved variable causes exit code 2

For `credential` type variables: values are masked in log output (replaced with `****`). For `string` and `url` types: values are shown in full.

Variables are resolved **before execution starts** (fail-fast). Every `${VAR}` reference in every step field is resolved in a single pass. If any variable cannot be resolved, the executor prints the missing variables and exits immediately.

## Step Execution

### Action Dispatch

The executor handles each action type:

| Action | Implementation |
|--------|---------------|
| `navigate` | `driver.get(resolved_value)`. If `wait_for_load` is true (default), waits for page load. |
| `click` | `target.click(selector)`. `target` is driver or iframe handle per `frame_context`. |
| `type` | If `clear_first`, calls `target.clear(selector)` first. Then `target.type(selector, resolved_value)`. |
| `select` | `target.select_option(selector, value=resolved_value)`. |
| `scroll` | `driver.run_js(f"window.scrollBy(0, {value})")`. |
| `wait` | If `selector`: `target.wait_for_element(selector, wait=timeout_s)`. If `value` only: `time.sleep(ms/1000)`. |
| `wait_for_download` | Handled by NetworkMonitor (see below). |
| `wait_for_response` | Handled by NetworkMonitor (see below). |
| `press_key` | CDP key dispatch (same as actions.py pattern). |
| `hover` | JS getBoundingClientRect + CDP mouseMoved (same as actions.py pattern). |
| `clear` | `target.clear(selector)`. |

### Iframe Context

The `frame_context` field on a step is a CSS selector for the iframe containing the target element. The executor calls `driver.select_iframe(frame_context)` to get a scoped handle, then executes the action on that handle.

For nested iframes using `>>>` syntax (e.g., `"iframe#outer >>> iframe#inner"`): split on `>>>`, navigate level by level via `select_iframe()`.

If `frame_context` is `None`, the action executes on the main page (`driver`).

### Shadow DOM

The `shadow_pierce` field is treated as a documentation flag. The selector itself should contain `>>>` pierce syntax if shadow DOM traversal is needed. Botasaurus-driver handles `>>>` natively. The executor passes the selector through as-is.

### Look-Ahead for Network Monitoring

Before executing each step, the executor checks if the **next** step is `wait_for_download` or `wait_for_response`. If so, it starts the `NetworkMonitor` before executing the current step. This ensures the monitor captures the network event triggered by the current step's action.

```python
for i, step in enumerate(steps):
    next_step = steps[i + 1] if i + 1 < len(steps) else None

    # Start monitoring if next step needs it
    if next_step and next_step.action in ("wait_for_download", "wait_for_response"):
        monitor.start(driver, url_pattern=next_step.url_pattern)

    # Execute current step
    result = execute_step(driver, step)

    # If this IS a wait step, the monitor was already started by previous iteration
    if step.action == "wait_for_download":
        download_events = monitor.wait_for_download(step.timeout_ms or default_timeout)
        monitor.stop()
    elif step.action == "wait_for_response":
        events = monitor.query(step.url_pattern)
        monitor.stop()
```

### Error Handling

Error policy resolution: step-level `on_error` overrides global `settings.on_error`.

| Policy | Behavior |
|--------|----------|
| `stop` | Log error, capture screenshot, exit with code 1 |
| `continue` | Log error, capture screenshot, proceed to next step |
| `retry` | V1: treated as `stop` with a warning logged |

### Timing

Between each step, the executor pauses for `settings.step_delay_ms` (default 500ms). Per-step `timeout_ms` overrides `settings.default_timeout_ms` for wait-based actions.

## Output Format

Each step emits a JSON line to stdout:

```json
{"step": 1, "name": "Navigate to ADP sign-in", "action": "navigate", "status": "ok", "elapsed_ms": 1200}
{"step": 2, "name": "Enter username", "action": "type", "status": "ok", "elapsed_ms": 340}
{"step": 5, "name": "Click Sign In", "action": "click", "status": "error", "elapsed_ms": 15023, "error": "Element not found: #signBtn", "screenshot": "screenshots/step-5-error.png"}
```

**Fields per line:**
- `step` — step order number
- `name` — human-readable step name
- `action` — action type
- `status` — `"ok"` or `"error"`
- `elapsed_ms` — step execution time
- `error` — error message (only on failure)
- `screenshot` — path to failure screenshot (only on failure)
- `file` — downloaded filename (only for `wait_for_download`)

**Summary line at end:**

```json
{"summary": true, "total_steps": 9, "passed": 8, "failed": 1, "elapsed_ms": 23400, "status": "failed"}
```

## Dry Run Mode

`--dry-run` validates and prints without executing:

1. Parse and validate the workflow JSON
2. Resolve all variables (CLI args → env → defaults)
3. Print the execution plan:

```json
{"dry_run": true, "name": "adp-report-download", "total_steps": 9, "variables_resolved": 3}
{"step": 1, "action": "navigate", "value": "https://online.adp.com/signin/v1/..."}
{"step": 2, "action": "type", "selector": "#login-form_username", "value": "****"}
{"step": 3, "action": "click", "selector": "[data-testid='verifUseridBtn']"}
```

Credential values are masked with `****` in dry-run output.

## Failure Screenshots

When a step fails and the `screenshot-dir` exists (created on first failure):
- Screenshot filename: `step-{order}-error-{timestamp}.png`
- Captured via `driver.save_screenshot(path)`
- Path included in the JSON log line's `screenshot` field

## Testing Strategy

### Unit Tests (no browser)
- Variable resolution: CLI args → env → defaults → error
- Variable masking for credential types
- Workflow JSON loading and validation
- Step ordering validation
- Dry-run output formatting
- Look-ahead logic for network monitoring steps
- Error policy resolution (step-level overrides global)

### Integration Tests (with browser)
- Navigate to a test page and verify URL
- Click/type/select actions
- iframe context switching
- Download detection via NetworkMonitor
- Screenshot capture on failure
- Full workflow execution end-to-end

## Non-Goals (V1)

- `retry` error policy (parsed, treated as `stop`)
- Parallel step execution
- Conditional branching
- Loop constructs
- Extracted variables propagated between steps
- Progress callbacks or webhook notifications
- GUI or web dashboard
