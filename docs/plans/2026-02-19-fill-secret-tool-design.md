# Design: `fill_secret` MCP Tool

**Date:** 2026-02-19
**Status:** Approved
**Problem:** During interactive browser sessions, credentials are typed in plaintext via `execute_action_tool(action="type", value="the_password")`, exposing them in the Claude conversation context and session history. The `.env` file holds credentials locally but the MCP server never reads it.

## Goal

Keep credential values completely out of the conversation context. Claude provides a `.env` variable name and a CSS selector; the MCP server reads the actual value server-side and injects it into the browser field. The value never appears in tool parameters, tool responses, or session history.

## Approach: Dedicated `fill_secret` Tool

A new MCP tool alongside the existing 7 tools. Chosen over extending `execute_action_tool` (muddied interface, ambiguous parameters) and over variable resolution middleware (weaker security boundary).

## Tool Interface

```python
@mcp.tool()
async def fill_secret(
    session_id: str,
    env_var: str,
    selector: str,
    frame_context: str | None = None,
    clear_first: bool = True,
    wait_after: int = 500,
    ctx: Context[ServerSession, AppContext] = None,
) -> dict:
    """Type a secret value from .env into a form field without exposing it.

    Args:
        session_id: Active session ID.
        env_var: Name of the environment variable in .env (e.g., 'PAYCOM_PASSWORD').
        selector: CSS selector of the target input field.
        frame_context: Iframe selector path. Use 'main' or omit for top-level.
        clear_first: Clear the field before typing. Default: true.
        wait_after: Milliseconds to wait after typing. Default: 500.
    """
```

### Usage Flow

1. Claude scouts the page, discovers a password field via `find_elements`
2. Claude calls `fill_secret(session_id="abc", env_var="PAYCOM_PASSWORD", selector="input#txtPassword")`
3. Server reads `PAYCOM_PASSWORD` from `.env`, types it into the field
4. Claude receives: `{"success": true, "env_var": "PAYCOM_PASSWORD", "selector": "input#txtPassword", "chars_typed": 22}`
5. The actual password value never enters the conversation

## .env Loading

### Location Strategy

Search order:
1. `BROWSER_SCOUT_ENV_FILE` environment variable (if set) -- absolute path to a custom `.env`
2. `.env` in the server's working directory (default -- this is `${CLAUDE_PLUGIN_ROOT}` per `.mcp.json`)

For non-default locations, configure in `.mcp.json`:
```json
{
  "mcpServers": {
    "browser-scout": {
      "command": "uv",
      "args": ["run", "--directory", "${CLAUDE_PLUGIN_ROOT}", "browser-scout"],
      "env": {
        "BROWSER_SCOUT_ENV_FILE": "/path/to/custom/.env"
      }
    }
  }
}
```

### Loading Behavior

- **Lazy:** Load on first `fill_secret` call, not at server startup
- **Cached:** Store in `AppContext.env_vars: dict[str, str] | None`
- **Dependency:** `python-dotenv` for robust parsing (handles quotes, comments, multiline, exports)

## Response Model

```python
class FillSecretResult(BaseModel):
    success: bool
    env_var: str              # "PAYCOM_PASSWORD"
    selector: str             # "input#txtPassword"
    chars_typed: int          # 22
    url_changed: bool = False
    current_url: str = ""
    error: str | None = None
    elapsed_ms: int = 0
```

No value characters are exposed -- `chars_typed` confirms the value was found and typed.

### Error Handling

- **Variable not found:** `"Environment variable 'TYPO_VAR' not found. Check your .env file."` -- never enumerate available names
- **`.env` file not found:** `"No .env file found. Expected at: /path/to/.env"` -- include the path so the user can create/locate it
- **Selector not found:** Standard element-not-found error, same as `execute_action_tool`

## History Integration

Records a standard `ActionRecord` with the env var reference instead of the actual value:

```python
ActionRecord(
    action="type",
    selector="input#txtPassword",
    value="${PAYCOM_PASSWORD}",    # reference, not the real value
    frame_context=frame_context,
    success=True,
    url_before=url_before,
    url_after=url_after,
    timestamp=timestamp,
)
```

This integrates naturally with `WorkflowConverter` -- the value is already parameterized.

## WorkflowConverter Update

The converter needs a small update to handle pre-parameterized values:

- When a step's `value` starts with `${`, skip the auto-detection regex logic
- Pass the `${VAR_NAME}` through as-is
- Create a `WorkflowVariable(type="credential")` entry for each unique `${VAR}` found in history
- This handles any env var name, not just those matching password/username patterns

## Execution Logic

```
1. Look up env_var in cached .env dict (lazy-load if needed)
2. Resolve frame context (reuse _resolve_target from actions.py)
3. If clear_first: target.clear(selector)
4. target.type(selector, secret_value)
5. Wait wait_after ms
6. Check for URL change
7. Record ActionRecord with value="${ENV_VAR}" (not the real value)
8. Invalidate element cache
9. Return FillSecretResult with chars_typed=len(secret_value)
```

## Files to Modify

| File | Change |
|------|--------|
| `src/browser_scout/server.py` | Add `fill_secret` tool, add `env_vars` to `AppContext`, add `.env` loading helper |
| `src/browser_scout/models.py` | Add `FillSecretResult` model |
| `src/browser_scout/workflow.py` | Update converter to recognize pre-parameterized `${VAR}` values |
| `pyproject.toml` | Add `python-dotenv` dependency |

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Dedicated tool vs. extending `execute_action_tool` | Clean separation; Claude cannot accidentally pass a `value` parameter containing the secret |
| No masked value in response | Even partial character exposure defeats the security goal; `chars_typed` provides sufficient confirmation |
| No variable name enumeration on error | Available names are metadata about configured secrets; revealing them leaks information |
| `clear_first` defaults to True | Pre-filled fields (password managers, autofill, retries) are common; clearing first is safer |
| Dropped `shadow_pierce` parameter | It's a no-op in the existing codebase; carrying it forward would be dishonest |
| Lazy .env loading | Avoids holding secrets in memory when `fill_secret` is never called |
| CSS selectors only | Consistent with all existing tools; `find_elements` outputs CSS selectors |
