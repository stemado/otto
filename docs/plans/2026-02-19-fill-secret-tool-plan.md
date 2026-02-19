# `fill_secret` Tool Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a new `fill_secret` MCP tool that injects `.env` credential values into browser form fields without exposing them in the conversation context.

**Architecture:** A dedicated MCP tool reads from `.env` via `python-dotenv`, types the value into the target element server-side, records the action in history with a `${VAR_NAME}` reference instead of the real value, and returns only the character count to Claude. The `WorkflowConverter` is updated to pass through pre-parameterized values.

**Tech Stack:** Python 3.11+, python-dotenv, Pydantic v2, FastMCP, botasaurus-driver

**Design Doc:** `docs/plans/2026-02-19-fill-secret-tool-design.md`

---

### Task 1: Add `python-dotenv` Dependency

**Files:**
- Modify: `pyproject.toml:6-9`

**Step 1: Add the dependency**

In `pyproject.toml`, add `python-dotenv` to the dependencies list:

```toml
dependencies = [
    "mcp[cli]>=1.0.0",
    "botasaurus-driver>=4.0.0",
    "pydantic>=2.0.0",
    "python-dotenv>=1.0.0",
]
```

**Step 2: Install**

Run: `uv sync`
Expected: Resolves and installs `python-dotenv`. No errors.

**Step 3: Verify import works**

Run: `uv run python -c "from dotenv import dotenv_values; print('OK')"`
Expected: Prints `OK`

**Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add python-dotenv dependency for fill_secret tool"
```

---

### Task 2: Add `FillSecretResult` Model

**Files:**
- Modify: `src/browser_scout/models.py:170-176` (after `MonitorResult`)
- Test: `tests/test_models.py`

**Step 1: Write the failing tests**

Add to the end of `tests/test_models.py`:

```python
from browser_scout.models import FillSecretResult


def test_fill_secret_result_success():
    result = FillSecretResult(
        success=True,
        env_var="PAYCOM_PASSWORD",
        selector="input#txtPassword",
        chars_typed=22,
        current_url="https://paycom.com/login",
    )
    assert result.success is True
    assert result.env_var == "PAYCOM_PASSWORD"
    assert result.chars_typed == 22
    assert result.url_changed is False  # default
    assert result.error is None  # default


def test_fill_secret_result_error():
    result = FillSecretResult(
        success=False,
        env_var="MISSING_VAR",
        selector="input#pwd",
        chars_typed=0,
        error="Environment variable 'MISSING_VAR' not found. Check your .env file.",
    )
    assert result.success is False
    assert result.error is not None
    assert result.chars_typed == 0


def test_fill_secret_result_serialization():
    result = FillSecretResult(
        success=True,
        env_var="PAYCOM_PASSWORD",
        selector="input#txtPassword",
        chars_typed=22,
    )
    data = result.model_dump(exclude_none=True)
    assert "error" not in data  # None fields excluded
    assert data["chars_typed"] == 22
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_models.py -v -k "fill_secret"`
Expected: FAIL — `ImportError: cannot import name 'FillSecretResult'`

**Step 3: Implement FillSecretResult**

Add to `src/browser_scout/models.py` after the `MonitorResult` class (after line 176):

```python
class FillSecretResult(BaseModel):
    """Result of filling a secret value into a form field."""

    success: bool
    env_var: str = Field(description="Name of the .env variable used")
    selector: str = Field(description="CSS selector of the target field")
    chars_typed: int = Field(default=0, description="Number of characters typed")
    url_changed: bool = Field(default=False)
    current_url: str = Field(default="")
    error: str | None = Field(default=None)
    elapsed_ms: int = Field(default=0)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_models.py -v -k "fill_secret"`
Expected: 3 PASSED

**Step 5: Commit**

```bash
git add src/browser_scout/models.py tests/test_models.py
git commit -m "feat: add FillSecretResult model for fill_secret tool"
```

---

### Task 3: Implement `.env` Loading Helper

**Files:**
- Create: `src/browser_scout/secrets.py`
- Test: `tests/test_secrets.py`

**Step 1: Write the failing tests**

Create `tests/test_secrets.py`:

```python
"""Tests for .env secret loading."""

import os
import pytest
from browser_scout.secrets import load_env_vars, EnvLoadError


@pytest.fixture
def env_file(tmp_path):
    """Create a temporary .env file for testing."""
    env = tmp_path / ".env"
    env.write_text(
        "# Test credentials\n"
        "TEST_USERNAME=admin\n"
        "TEST_PASSWORD=s3cret!value\n"
        "TEST_EMPTY=\n"
        'TEST_QUOTED="quoted value"\n'
    )
    return str(env)


def test_load_env_vars_reads_file(env_file):
    vars = load_env_vars(env_file)
    assert vars["TEST_USERNAME"] == "admin"
    assert vars["TEST_PASSWORD"] == "s3cret!value"


def test_load_env_vars_handles_quoted_values(env_file):
    vars = load_env_vars(env_file)
    assert vars["TEST_QUOTED"] == "quoted value"


def test_load_env_vars_includes_empty_values(env_file):
    vars = load_env_vars(env_file)
    assert "TEST_EMPTY" in vars


def test_load_env_vars_skips_comments(env_file):
    vars = load_env_vars(env_file)
    # Should not have a key starting with '#'
    assert not any(k.startswith("#") for k in vars)


def test_load_env_vars_missing_file():
    with pytest.raises(EnvLoadError, match="No .env file found"):
        load_env_vars("/nonexistent/path/.env")


def test_load_env_vars_default_path(monkeypatch, env_file):
    """When no explicit path, uses BROWSER_SCOUT_ENV_FILE env var."""
    monkeypatch.setenv("BROWSER_SCOUT_ENV_FILE", env_file)
    vars = load_env_vars()
    assert vars["TEST_USERNAME"] == "admin"


def test_load_env_vars_default_cwd(monkeypatch, tmp_path):
    """Falls back to .env in current working directory."""
    env = tmp_path / ".env"
    env.write_text("CWD_VAR=from_cwd\n")
    monkeypatch.delenv("BROWSER_SCOUT_ENV_FILE", raising=False)
    monkeypatch.chdir(tmp_path)
    vars = load_env_vars()
    assert vars["CWD_VAR"] == "from_cwd"


def test_load_env_vars_no_file_anywhere(monkeypatch, tmp_path):
    """Raises EnvLoadError when no .env exists anywhere."""
    monkeypatch.delenv("BROWSER_SCOUT_ENV_FILE", raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(EnvLoadError, match="No .env file found"):
        load_env_vars()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_secrets.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'browser_scout.secrets'`

**Step 3: Implement the secrets module**

Create `src/browser_scout/secrets.py`:

```python
"""Secret loading from .env files — keeps credentials out of conversation context."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values


class EnvLoadError(Exception):
    """Raised when the .env file cannot be loaded."""


def load_env_vars(env_file: str | None = None) -> dict[str, str]:
    """Load environment variables from a .env file.

    Search order:
    1. Explicit env_file path (if provided)
    2. BROWSER_SCOUT_ENV_FILE environment variable
    3. .env in the current working directory

    Returns:
        Dict of variable name -> value.

    Raises:
        EnvLoadError: If no .env file is found at any search location.
    """
    path = _resolve_env_path(env_file)

    values = dotenv_values(path)
    # dotenv_values returns OrderedDict[str, str | None]; normalize None -> ""
    return {k: (v or "") for k, v in values.items()}


def _resolve_env_path(env_file: str | None) -> Path:
    """Find the .env file path using the search order."""
    # 1. Explicit path
    if env_file:
        p = Path(env_file)
        if not p.is_file():
            raise EnvLoadError(f"No .env file found at: {p}")
        return p

    # 2. BROWSER_SCOUT_ENV_FILE environment variable
    env_path = os.environ.get("BROWSER_SCOUT_ENV_FILE")
    if env_path:
        p = Path(env_path)
        if not p.is_file():
            raise EnvLoadError(f"No .env file found at: {p} (from BROWSER_SCOUT_ENV_FILE)")
        return p

    # 3. Current working directory
    p = Path.cwd() / ".env"
    if p.is_file():
        return p

    raise EnvLoadError(
        "No .env file found. Expected at: .env (in working directory) "
        "or set BROWSER_SCOUT_ENV_FILE environment variable."
    )
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_secrets.py -v`
Expected: All 8 PASSED

**Step 5: Commit**

```bash
git add src/browser_scout/secrets.py tests/test_secrets.py
git commit -m "feat: add secrets module for .env loading with search order"
```

---

### Task 4: Update WorkflowConverter for Pre-Parameterized Values

**Files:**
- Modify: `src/browser_scout/workflow.py:114-171`
- Test: `tests/test_workflow.py`

**Step 1: Write the failing tests**

Add to the end of `tests/test_workflow.py`:

```python
def test_converter_preserves_pre_parameterized_value():
    """fill_secret records ${VAR} in history — converter should pass it through."""
    history = _make_history([
        ActionRecord(action="type", selector="input#txtPassword", value="${PAYCOM_PASSWORD}", success=True, timestamp="T1"),
    ])
    workflow = WorkflowConverter.from_history(history, name="test")
    # Value should pass through unchanged
    assert workflow.steps[0].value == "${PAYCOM_PASSWORD}"
    # Should create a credential variable for it
    assert "PAYCOM_PASSWORD" in workflow.variables
    assert workflow.variables["PAYCOM_PASSWORD"].type == "credential"


def test_converter_preserves_multiple_pre_parameterized():
    """Multiple pre-parameterized vars from fill_secret."""
    history = _make_history([
        ActionRecord(action="type", selector="#client_code", value="${PAYCOM_CLIENT_CODE}", success=True, timestamp="T1"),
        ActionRecord(action="type", selector="#username", value="${PAYCOM_USERNAME}", success=True, timestamp="T2"),
        ActionRecord(action="type", selector="#password", value="${PAYCOM_PASSWORD}", success=True, timestamp="T3"),
    ])
    workflow = WorkflowConverter.from_history(history, name="test")
    assert workflow.steps[0].value == "${PAYCOM_CLIENT_CODE}"
    assert workflow.steps[1].value == "${PAYCOM_USERNAME}"
    assert workflow.steps[2].value == "${PAYCOM_PASSWORD}"
    assert len(workflow.variables) == 3
    for var in workflow.variables.values():
        assert var.type == "credential"


def test_converter_mixed_pre_parameterized_and_auto_detected():
    """Pre-parameterized fill_secret values coexist with auto-detected ones."""
    history = _make_history([
        ActionRecord(action="type", selector="#username", value="${PAYCOM_USERNAME}", success=True, timestamp="T1"),
        ActionRecord(action="type", selector="#other_password_field", value="raw_secret", success=True, timestamp="T2"),
    ])
    workflow = WorkflowConverter.from_history(history, name="test")
    # Pre-parameterized: passed through
    assert workflow.steps[0].value == "${PAYCOM_USERNAME}"
    assert "PAYCOM_USERNAME" in workflow.variables
    # Auto-detected: the second field has "password" in its selector
    assert workflow.steps[1].value == "${PASSWORD}"
    assert "PASSWORD" in workflow.variables
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_workflow.py -v -k "pre_parameterized"`
Expected: FAIL — first test shows `value == "${PASSWORD}"` instead of `"${PAYCOM_PASSWORD}"` because the converter's regex matches the selector `input#txtPassword` and overwrites the pre-parameterized value.

**Step 3: Update the WorkflowConverter**

In `src/browser_scout/workflow.py`, modify the `from_history` method. The key change is: **skip auto-detection for values already starting with `${`**, and collect pre-parameterized variables.

Replace the `from_history` method body (lines 101-171) with:

```python
    @staticmethod
    def from_history(
        history: SessionHistory,
        name: str,
        description: str = "",
    ) -> Workflow:
        """Build a Workflow from a SessionHistory.

        - Filters to successful actions only
        - Auto-generates human-readable step names
        - Preserves pre-parameterized ${VAR} values (from fill_secret)
        - Parameterizes credential fields (password/username) for raw values
        - Strips 'main' frame_context (it's the default)
        """
        successful = [a for a in history.actions if a.success]

        # First pass: identify credential fields (skip pre-parameterized values)
        password_indices: set[int] = set()
        username_indices: set[int] = set()

        for i, action in enumerate(successful):
            if action.action == "type" and action.selector:
                # Skip values already parameterized by fill_secret
                if action.value and action.value.startswith("${"):
                    continue
                if _PASSWORD_PATTERNS.search(action.selector):
                    password_indices.add(i)
                    # Look backward for the nearest type action on a username-like field
                    for j in range(i - 1, -1, -1):
                        prev = successful[j]
                        if prev.action == "type" and prev.selector and _USERNAME_PATTERNS.search(prev.selector):
                            # Don't override pre-parameterized values
                            if prev.value and prev.value.startswith("${"):
                                break
                            username_indices.add(j)
                            break

        # Build variables — start with auto-detected ones
        variables: dict[str, WorkflowVariable] = {}
        if password_indices:
            variables["PASSWORD"] = WorkflowVariable(
                type="credential", default="your_password", description="Login password",
            )
        if username_indices:
            variables["USERNAME"] = WorkflowVariable(
                type="credential", default="your_username", description="Login username",
            )

        # Collect pre-parameterized variables from fill_secret
        for action in successful:
            if action.value and action.value.startswith("${") and action.value.endswith("}"):
                var_name = action.value[2:-1]
                if var_name not in variables:
                    variables[var_name] = WorkflowVariable(
                        type="credential", default="", description=f"Value from .env: {var_name}",
                    )

        # Second pass: build steps
        steps: list[WorkflowStep] = []
        for i, action in enumerate(successful):
            value = action.value
            # Only apply auto-detection to raw (non-parameterized) values
            if not (value and value.startswith("${")):
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
```

**Step 4: Run all workflow tests**

Run: `uv run pytest tests/test_workflow.py -v`
Expected: ALL PASSED (existing + 3 new tests)

**Step 5: Commit**

```bash
git add src/browser_scout/workflow.py tests/test_workflow.py
git commit -m "feat: update WorkflowConverter to preserve pre-parameterized values"
```

---

### Task 5: Implement `fill_secret` Tool

**Files:**
- Modify: `src/browser_scout/server.py`

**Step 1: Update imports in server.py**

Add `FillSecretResult` to the imports from `.models` (line 16-24), and add the secrets import:

```python
from .models import (
    ActionRecord,
    ActionResult,
    FillSecretResult,
    FindElementsResult,
    MonitorResult,
    ScoutReport,
    SessionCloseResult,
    SessionHistory,
    SessionInfo,
)
from .secrets import load_env_vars, EnvLoadError
```

**Step 2: Add `env_vars` to AppContext**

Update the `AppContext` dataclass (line 31-36):

```python
@dataclass
class AppContext:
    """Holds all browser sessions across the server's lifetime."""

    sessions: dict[str, BrowserSession] = field(default_factory=dict)
    max_sessions: int = 1
    env_vars: dict[str, str] | None = field(default=None)
```

**Step 3: Add the `_load_env` helper function**

Add after the `_get_session` function (after line 68):

```python
def _load_env(app_ctx: AppContext) -> dict[str, str]:
    """Lazy-load .env variables on first use. Raises ValueError on failure."""
    if app_ctx.env_vars is None:
        try:
            app_ctx.env_vars = load_env_vars()
        except EnvLoadError as e:
            raise ValueError(str(e)) from e
    return app_ctx.env_vars
```

**Step 4: Add the `fill_secret` tool**

Add the tool after `execute_action_tool` (after line 312, before the `# --- Tool: monitor_network ---` comment):

```python
# --- Tool: fill_secret ---


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
    """Type a secret value from .env into a form field without exposing it in the conversation.

    The server reads the value from the .env file and types it directly into the
    target element. The actual value never appears in tool parameters or responses.

    Args:
        session_id: Active session ID.
        env_var: Name of the environment variable in .env (e.g., 'PAYCOM_PASSWORD').
        selector: CSS selector of the target input field.
        frame_context: Iframe selector path for the target element. Use 'main' or omit for top-level.
        clear_first: Clear the field before typing. Default: true.
        wait_after: Milliseconds to wait after typing. Default: 500.
    """
    import time
    from datetime import datetime, timezone

    from .actions import _resolve_target

    app_ctx = _get_ctx(ctx)
    session = _get_session(app_ctx, session_id)

    start = time.perf_counter()
    timestamp = datetime.now(timezone.utc).isoformat()

    # Load the secret value server-side
    try:
        env = _load_env(app_ctx)
    except ValueError as e:
        return FillSecretResult(
            success=False, env_var=env_var, selector=selector,
            error=str(e),
        ).model_dump(exclude_none=True)

    if env_var not in env:
        return FillSecretResult(
            success=False, env_var=env_var, selector=selector,
            error=f"Environment variable '{env_var}' not found. Check your .env file.",
        ).model_dump(exclude_none=True)

    secret_value = env[env_var]

    # Type the value into the field
    try:
        url_before = session.driver.current_url
    except Exception:
        url_before = ""

    error = None
    try:
        target = _resolve_target(session.driver, frame_context)
        if clear_first:
            target.clear(selector)
        target.type(selector, secret_value)
    except Exception as e:
        error = str(e)

    if wait_after > 0:
        await asyncio.sleep(wait_after / 1000)

    try:
        url_after = session.driver.current_url
    except Exception:
        url_after = url_before

    elapsed = int((time.perf_counter() - start) * 1000)

    # Record in history with reference, NOT the actual value
    record = ActionRecord(
        action="type",
        selector=selector,
        value=f"${{{env_var}}}",
        frame_context=frame_context,
        success=error is None,
        url_before=url_before,
        url_after=url_after,
        timestamp=timestamp,
        error=error,
    )
    session.history.record_action(record)
    if url_before != url_after:
        session.history.record_navigation(url_after)
    session.invalidate_element_cache()

    result = FillSecretResult(
        success=error is None,
        env_var=env_var,
        selector=selector,
        chars_typed=len(secret_value) if error is None else 0,
        url_changed=url_before != url_after,
        current_url=url_after,
        error=error,
        elapsed_ms=elapsed,
    )

    if result.success:
        await ctx.info(f"Secret '{env_var}' typed into '{selector}' ({result.chars_typed} chars)")
    else:
        await ctx.warning(f"fill_secret failed: {error}")

    return result.model_dump(exclude_none=True)
```

**Step 5: Run existing tests to check for regressions**

Run: `uv run pytest tests/ -v --ignore=tests/test_integration.py`
Expected: ALL PASSED

**Step 6: Commit**

```bash
git add src/browser_scout/server.py
git commit -m "feat: add fill_secret MCP tool for secure credential injection"
```

---

### Task 6: Update Documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `skills/browser-scout/SKILL.md`

**Step 1: Update CLAUDE.md workflow pattern**

In the `#### Workflow Pattern` section, add step 4.5 between Act and Scout-again:

```markdown
4.5. **Fill secrets** — When a form field needs a credential, use `fill_secret` with the `.env` variable name and CSS selector. The value is injected server-side and never appears in the conversation.
```

Add a new section after `#### Credential Parameterization — MANDATORY`:

```markdown
#### Secure Credential Injection — `fill_secret`

When filling credential fields (passwords, API keys, tokens), use the `fill_secret` tool instead of `execute_action_tool`. This keeps the credential value out of the conversation:

- `fill_secret(session_id, env_var="PAYCOM_PASSWORD", selector="input#txtPassword")`
- The server reads the value from `.env` and types it into the field
- The response only confirms how many characters were typed (no value exposure)
- Session history records `${PAYCOM_PASSWORD}` instead of the actual password

The `.env` file is found automatically in the server's working directory. For custom locations, set `BROWSER_SCOUT_ENV_FILE` in `.mcp.json` env config.
```

**Step 2: Update SKILL.md workflow**

In the `## Workflow` section, add after step 4:

```markdown
4b. **Fill secrets** — Use `fill_secret` for credential fields (passwords, tokens, API keys). Pass the `.env` variable name and selector — the value stays server-side.
```

Add to the `## Composing Playwright Scripts` section:

```markdown
### Credentials from `fill_secret`

When `fill_secret` was used during the session, the history already contains parameterized values like `${PAYCOM_PASSWORD}`. Use these variable names directly in the generated Playwright script's configuration section. Do not attempt to resolve or look up the actual values.
```

**Step 3: Commit**

```bash
git add CLAUDE.md skills/browser-scout/SKILL.md
git commit -m "docs: document fill_secret tool in CLAUDE.md and SKILL.md"
```

---

### Task 7: Final Verification

**Step 1: Run all unit tests**

Run: `uv run pytest tests/ -v --ignore=tests/test_integration.py`
Expected: ALL PASSED (models + secrets + workflow tests)

**Step 2: Verify the tool registers with MCP**

Run: `uv run python -c "from browser_scout.server import mcp; print([t.name for t in mcp._tool_manager._tools.values()])"`
Expected: List includes `fill_secret` alongside the existing 7 tools.

**Step 3: Verify .env loading end-to-end**

Run: `uv run python -c "from browser_scout.secrets import load_env_vars; v = load_env_vars(); print(f'{len(v)} vars loaded')"` (from the project root)
Expected: Prints `5 vars loaded` (the 5 variables in .env)

**Step 4: Check git status is clean**

Run: `git status`
Expected: Clean working tree, all changes committed.
