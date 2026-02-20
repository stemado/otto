## Workflow Executor — Implementation Plan

### Problem Statement

Browser-scout generates workflow JSON files via `/export-workflow`, but nothing can replay them without Claude in the loop. Building a standalone `WorkflowExecutor` + `workflow-run` CLI enables:
- Scheduled/automated workflow execution (nightly report downloads)
- CI/CD integration
- Workflow testing and validation without an MCP server

### Constraints

- No schema changes to `workflow.py` models
- Reuse `NetworkMonitor` from `network.py` (no reimplementation)
- Import `_get_key_map` from `actions.py` (no duplication)
- Synchronous execution (botasaurus-driver is sync)
- No new pip dependencies
- `retry` error policy: parsed but treated as `stop` in V1

### Approach

Single new module `src/browser_scout/executor.py` with 4 independently testable layers:

1. **Variable resolver** — resolves `${VAR}` references (CLI args → env → defaults)
2. **Error policy + look-ahead** — step-level override of global policy; pre-start monitoring before wait steps
3. **WorkflowExecutor class** — orchestrates steps with timing, error handling, screenshots
4. **CLI entry point** — argparse, dry-run mode, JSON-lines output

### Impact Analysis

| Action | File | Description |
|--------|------|-------------|
| Create | `src/browser_scout/executor.py` | Core executor + CLI (~300 lines) |
| Create | `tests/test_executor.py` | Unit tests (~200 lines) |
| Modify | `pyproject.toml` | Add `workflow-run` script entry point |

No changes to existing browser-scout functionality.

### Sequence

---

#### Task 1: Variable Resolver + Error Policy + Look-Ahead

Create `executor.py` with the foundational functions (no browser dependency):

- `resolve_variables(workflow, cli_vars)` — resolves `${VAR}` in step fields
  - Priority: CLI args → env vars → non-empty defaults → exit(2)
  - Resolves in `selector`, `value`, and `url_pattern` fields
  - Returns a new Workflow with resolved steps
- `resolve_error_policy(step_policy, global_policy)` — step overrides global, retry→stop
- `needs_pre_monitoring(next_step)` — True if next step is `wait_for_download` or `wait_for_response`
- `mask_credential_value(original_ref, resolved_value, variables)` — masks credential values with `****`

Tests (all unit, no browser):
- Variable resolution: CLI args, env vars, defaults, priority ordering, unresolved error, multi-var in one field, var in selector, no-vars passthrough
- Error policy: step override, global fallback, retry→stop
- Look-ahead: download, response, regular step, None
- Credential masking: credential type, non-credential, no variable ref

#### Task 2: WorkflowExecutor Class + Step Dispatch

Add `WorkflowExecutor` class that takes a resolved `Workflow` and executes steps:

- `run()` — main execution loop with look-ahead, timing, error handling
- `_execute_step()` — action dispatch via match/case (mirrors `actions.py` patterns)
- `_capture_screenshot()` — failure screenshot capture
- `_resolve_target()` — iframe context resolution (reuses `actions.py` pattern)
- Import `_get_key_map` from `actions` module (no duplication)

Step dispatch covers all 11 action types: navigate, click, type, select, scroll, wait, wait_for_download, wait_for_response, press_key, hover, clear.

JSON-lines output per step: `{"step": N, "name": "...", "action": "...", "status": "ok|error", "elapsed_ms": N}`
Summary line at end: `{"summary": true, "total_steps": N, "passed": N, "failed": N, "elapsed_ms": N, "status": "ok|failed"}`

No new tests here — the executor requires a browser and is tested indirectly via dry-run.

#### Task 3: CLI Entry Point + Dry-Run

Add `main()` CLI function + `dry_run()`:

- argparse: `workflow-run <file> [--var KEY=VALUE] [--headless] [--download-dir] [--screenshot-dir] [--dry-run] [--timeout]`
- `dry_run()` — validates, resolves variables, prints JSON plan (credentials masked)
- `if __name__ == "__main__":` guard for `python -m browser_scout.executor` support

Tests (subprocess + direct):
- Dry-run valid workflow: verifies JSON output structure, credential masking
- Dry-run invalid JSON: exit code 2
- Dry-run missing file: exit code 2

#### Task 4: pyproject.toml Entry Point + Verification

- Add `workflow-run = "browser_scout.executor:main"` to `[project.scripts]`
- Reinstall package (`uv pip install -e .`)
- Verify `workflow-run --help` works
- Run full test suite (existing 50+ tests + new executor tests)

### Verification Strategy

**Unit tests (no browser, ~20 tests):**
- Variable resolution (8 tests)
- Error policy (4 tests)
- Look-ahead (4 tests)
- Credential masking (3 tests)
- Dry-run CLI (3 tests)

**Manual verification:**
- `workflow-run --help` shows usage
- `workflow-run --dry-run <workflow.json>` validates and prints plan
- Full project test suite still passes

**Definition of done:**
- All tests pass (existing + new)
- `workflow-run --help` works as installed script
- `workflow-run --dry-run` correctly validates, resolves, and prints a workflow
- No new pip dependencies

### Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| botasaurus-driver API differences | Medium | Mirror patterns from working `actions.py` |
| Subprocess tests fragile on Windows | Medium | Use direct function calls for unit tests, 1 subprocess test for CLI smoke |
| `NetworkMonitor.wait_for_download` may not detect filesystem downloads | Medium | Monitor detects `content-disposition: attachment` headers; filesystem polling is V2 |
| Importing `_get_key_map` from `actions` couples modules | Low | Preferable to duplication; key map is stable and static |

### Staff Engineer Self-Review

1. **REFINE: Importing `_get_key_map` from `actions.py`.** It's a private function (leading underscore). Making it importable across modules is technically violating the naming convention. Options: (a) rename to `get_key_map()` in `actions.py`, (b) extract to `keys.py`, (c) just import the private name and accept the coupling. Option (c) is simplest for V1 — both files are in the same package. If the key map ever needs to diverge between interactive and batch execution, we extract then.

2. **REFINE: Variable resolution uses `sys.exit(2)`.** A custom exception would be cleaner, but the spec mandates exit code 2. Since `main()` is the only caller path, `sys.exit` is acceptable. Tests handle it via `pytest.raises(SystemExit)`.

3. **NOTE: Look-ahead assumes `wait_for_*` immediately follows the triggering action.** If there's an intervening step between the trigger and the wait, the monitor misses the event. This matches the spec's design and is documented in the JSON schema section on step ordering.

4. **NOTE: Screenshot capture swallows exceptions.** If the screenshot dir is unwritable, the error is lost. Acceptable — screenshot failure shouldn't prevent step result reporting.

No BLOCKING concerns.
