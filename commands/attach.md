---
description: Attach to a paused otto-engine execution's browser for Hot Takeover
argument-hint: "[execution_id]"
allowed-tools:
  - "mcp__plugin_otto-marketplace_otto__*"
---

Attach to a browser owned by otto-engine that is currently paused. This enables Hot Takeover — you take interactive control of the browser while the engine's executor thread blocks, waiting for your resume instruction.

## Steps

1. **Determine the otto-engine base URL.**
   Default: `http://localhost:8000`. Check if the environment variable `OTTO_ENGINE_URL` is set and use that instead.

2. **Find the paused execution.**

   If the user provided an `execution_id` argument, use it directly.

   If no argument was provided, query the engine for all executions:
   ```
   GET {base_url}/api/executions
   ```
   Filter for executions with `status == "running"`. Present them to the user and ask which one to attach to.

3. **Get the browser connection info:**
   ```
   GET {base_url}/api/executions/{execution_id}/browser
   ```

   If the response shows `state` is `"running"` (not paused), offer to pause it:
   - Ask: "This execution is still running. Would you like to pause it so you can take over?"
   - If yes: `POST {base_url}/api/executions/{execution_id}/pause`
   - Then poll `GET /api/executions/{execution_id}/browser` every 2 seconds (up to 30 seconds) until `state` starts with `"paused"`.

   If the response is 404, tell the user the execution has no active browser session.

4. **Attach to the browser** by calling the `attach_session` MCP tool:
   - `host`: from the browser response's `cdp_host`
   - `port`: from the browser response's `cdp_port`
   - `execution_id`: the execution ID

5. **Auto-scout** — immediately call `scout_page_tool` with the new session ID to show the user what page the browser is on.

6. **Display pause context.** From the browser response, show:
   - Current state (paused_error, paused_handoff, paused_requested)
   - If `paused_at_step` is present: step name, action, reason, and error (if any)
   - The current page URL from the scout

7. **Remind the user** of their options:
   - Use OTTO tools normally (scout, find_elements, execute_action, etc.) to inspect and interact
   - Use `/resume` when ready to hand control back to the engine
   - Use `close_session` to detach without resuming (engine stays paused)

Use `httpx` for all HTTP calls to the otto-engine API. Handle connection errors gracefully — if the engine is unreachable, tell the user to check that otto-engine is running.
