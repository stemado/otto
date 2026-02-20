# Export Workflow Design

**Date:** 2026-02-19
**Status:** Approved
**Problem:** After completing a browser reconnaissance workflow (scout, find, click, type), there's no way to export it as a replayable Python script.

## Decision

Slash command approach: `/export-workflow` tells Claude to call `get_session_history`, then compose a Python + botasaurus-driver script from the action history. No new MCP tools or server code needed.

## Design

### Command: `/export-workflow`

**File:** `commands/export-workflow.md`

**Invocation:** `/export-workflow [workflow-name]` (name is optional, defaults to timestamp)

**What it does:**
1. Calls `get_session_history` for the active session
2. Filters to `actions` and `navigations` (ignores scouts, find_elements calls)
3. Maps each action to its botasaurus-driver equivalent
4. Extracts credentials to parameterized variables
5. Writes the script to `workflows/<name>.py`

### Data Contract

Only `actions[]` and `navigations[]` from session history are used:
- `navigations[0].url` becomes the initial `driver.get()` call
- Each `ActionRecord` maps to a driver method call based on its `action` field
- `type` actions targeting selectors containing "password" (case-insensitive) are treated as credentials

### Action Mapping

| Session Action | botasaurus-driver Code |
|---------------|----------------------|
| `navigate` | `driver.get(value)` |
| `click` | `driver.click(selector)` |
| `type` | `driver.type(selector, value)` |
| `select` | `driver.select_option(selector, value=value)` |
| `scroll` | `driver.run_js(f"window.scrollBy(0, {value})")` |
| `wait` (with selector) | `driver.wait_for_element(selector, wait=N)` |
| `wait` (without) | `time.sleep(N)` |
| `press_key` | CDP key dispatch (same as actions.py) |
| `hover` | JS-based mouse move (same as actions.py) |
| `clear` | `driver.clear(selector)` |

### Script Structure

```python
"""Workflow: <name>
Generated from browser-scout session on <date>.
"""
from botasaurus_driver import Driver

# --- Configuration ---
USERNAME = "your_username"
PASSWORD = "your_password"
BASE_URL = "<first navigation URL>"

def run_workflow():
    driver = Driver(headless=False)
    try:
        # Step 1: Navigate to <URL>
        driver.get(BASE_URL)
        # Step 2: <action description>
        driver.<method>(selector)
        # ...
    finally:
        driver.close()

if __name__ == "__main__":
    run_workflow()
```

### Credential Parameterization

- Any `type` action where the selector contains "password" → value extracted to `PASSWORD` variable
- Any `type` action targeting a field immediately before a password field → extracted to `USERNAME` variable
- All other `type` values are kept inline

## Scope

- **Create:** `commands/export-workflow.md`
- **No changes** to server.py, models.py, or any Python code

## Future

- JSON workflow recipe format for C# backend consumption
- Network wait integration for download workflows
