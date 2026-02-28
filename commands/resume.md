---
description: Resume a paused otto-engine execution after Hot Takeover
argument-hint: "<action> [step_index]"
allowed-tools:
  - "mcp__plugin_otto-marketplace_otto__*"
---

Resume a paused otto-engine execution, handing control back from the interactive OTTO session to the engine's executor.

## Arguments

- `action` (required): One of:
  - `retry` — Re-execute the step that was paused (useful after fixing an element or page state)
  - `continue` — Skip the paused step and advance to the next one
  - `abort` — Terminate the execution entirely
  - `jump <step_index>` — Jump to a specific step index (0-based)

- If the argument is `jump`, the next word is the step index (e.g., `/resume jump 5`).

## Steps

1. **Validate there's an active attached session.** Look through active sessions for one where `owns_browser` is False. If none found, tell the user: "No attached session found. Use /attach first."

2. **Determine the otto-engine base URL.**
   Default: `http://localhost:8000`. Check if the environment variable `OTTO_ENGINE_URL` is set and use that instead.

3. **Parse the action** from the user's argument:
   - If the argument starts with `jump`, extract the step index from the next word.
   - Valid actions: `retry`, `continue`, `abort`, `jump`.
   - If no argument provided or invalid, ask the user which action to take. Present the four options with descriptions.

4. **Send the resume instruction** to otto-engine:
   ```
   POST {base_url}/api/executions/{execution_id}/resume
   Content-Type: application/json

   {"action": "<action>", "step_index": <index_or_null>}
   ```
   Wait for the 200 acknowledgment.

5. **Detach the session.** Call `close_session` with the attached session's ID. This drops the CDP connection without killing Chrome — the engine takes back control.

6. **Report the result:**
   - "Resumed execution {execution_id} with action: {action}"
   - If action was `retry`: "The engine will re-execute the paused step."
   - If action was `continue`: "The engine will skip to the next step."
   - If action was `abort`: "The engine will terminate the execution."
   - If action was `jump`: "The engine will jump to step {step_index}."

Use `httpx` for the HTTP call. Handle errors gracefully — if the resume call fails (404, 422), explain what went wrong.
