---
description: Export the current browser session as a replayable workflow (Python script + portable JSON)
argument-hint: "[workflow-name]"
allowed-tools:
  - "mcp__plugin_browser-scout_browser-scout__*"
---

Generate both a self-contained Python script and a portable workflow JSON file from the current browser session. Follow these steps precisely:

## Step 1: Get the session history

Call `get_session_history` with the active session_id. If no session is active, tell the user they need to run a workflow first using `/scout`.

## Step 2: Extract the workflow steps

From the history, use ONLY these fields to build the script:
- **`navigations`** — the first entry's `url` becomes the initial `driver.get()` call
- **`actions`** — each successful action becomes a step in the script

**Ignore** `scouts` and `find_elements_calls` entirely — those were reconnaissance, not replay steps. Only include actions where `success` is `true`.

## Step 3: Map actions to botasaurus-driver code

Use this exact mapping for each action record:

| action | Code |
|--------|------|
| `navigate` | `driver.get(value)` |
| `click` | `driver.click(selector)` |
| `type` | `driver.type(selector, value)` |
| `select` | `driver.select_option(selector, value=value)` |
| `scroll` | `driver.run_js(f"window.scrollBy(0, {amount})")` |
| `wait` (with selector) | `driver.wait_for_element(selector, wait=timeout_seconds)` |
| `wait` (no selector) | `time.sleep(seconds)` |
| `press_key` | Use CDP dispatch pattern from botasaurus_driver.cdp |
| `hover` | Use JS getBoundingClientRect + CDP mouseMoved |
| `clear` | `driver.clear(selector)` |

If `frame_context` is present and not "main", wrap the action with `driver.select_iframe(frame_context)` to get the iframe handle, then call the method on that handle instead of the driver.

## Step 4: Parameterize credentials — MANDATORY

Scan all `type` actions for sensitive fields:
- If the **selector** contains "password" (case-insensitive) OR the action's value was typed into a password-type field: extract the value to a `PASSWORD` variable at the top of the script. Replace the inline value with the variable name.
- If a `type` action targets a selector containing "username", "user", "email", or "login" (case-insensitive): extract the value to a `USERNAME` variable.
- For any other potentially sensitive values (API keys, tokens), extract them to named variables.

**NEVER hardcode credentials in the script body.** Use placeholder values like `"your_username"` and `"your_password"` in the variable declarations.

## Step 5: Compose the script

Structure the script exactly like this:

```python
"""Workflow: <workflow-name>
Generated from browser-scout session on <date>.
Session: <session_id> | Actions: <count> | Duration: <if available>
"""
import time
from botasaurus_driver import Driver

# --- Configuration (update these before running) ---
USERNAME = "your_username"
PASSWORD = "your_password"
BASE_URL = "<first navigation URL>"


def run_workflow():
    """Replay the recorded browser workflow."""
    driver = Driver(headless=False)
    try:
        # Step 1: Navigate to starting page
        driver.get(BASE_URL)

        # Step 2: <human-readable description of what this action does>
        driver.<method>(selector, value)

        # ... one step per action, numbered sequentially ...

    finally:
        driver.close()


if __name__ == "__main__":
    run_workflow()
```

Rules for the script:
- Every step gets a **comment** explaining what it does in human terms (e.g., "Click the Login button", "Enter username")
- Steps are **numbered sequentially** starting from 1
- The `try/finally` block ensures the browser is always closed
- Add `time.sleep(0.5)` between steps that trigger page navigation (where `url_changed` is true in the action record)
- Import `time` only if sleep calls are needed
- Only include the `USERNAME`/`PASSWORD` variables if credentials were actually detected
- The script must be **self-contained** — runnable with just `python workflow.py` after installing botasaurus-driver

## Step 5b: Generate workflow JSON

In addition to the Python script, generate a portable workflow JSON file using the `WorkflowConverter` from `src/browser_scout/workflow.py`:

1. Build a `Workflow` model by calling `WorkflowConverter.from_history(history, name=workflow_name, description=description)`
   - `history` is the `SessionHistory` from Step 1
   - `workflow_name` is the slugified name from Step 6
   - `description` is a short summary derived from the key actions (e.g., "Log into ADP WFN and download report")
2. The converter automatically handles credential parameterization (same logic as Step 4) and step name generation
3. Serialize with `workflow.model_dump_json(exclude_none=True, indent=2)`

The JSON file is the portable, machine-parseable workflow definition. It can be consumed by any executor (Python, C#, etc.) without requiring Claude in the loop. See `docs/plans/2026-02-19-workflow-json-schema-design.md` for the full schema specification.

## Step 6: Determine the workflow name

- If the user provided a name as an argument, use it (slugified: lowercase, hyphens for spaces)
- If no name was provided, derive one from the workflow: e.g., "login-to-reports" based on the navigations and key actions
- Use the name for both the filename and the docstring

## Step 7: Write the files

Write both files to the `workflows/` directory in the current project. Create the directory if it doesn't exist:

- **Python script:** `workflows/<workflow-name>.py`
- **Workflow JSON:** `workflows/<workflow-name>.json`

Present both files to the user and tell them:

- The file paths where they were saved
- How to run the Python script: `python workflows/<name>.py`
- That the JSON file is the portable workflow definition for use with any executor
- What they need to update (credentials, BASE_URL if different environment)
- That botasaurus-driver must be installed: `pip install botasaurus-driver`
