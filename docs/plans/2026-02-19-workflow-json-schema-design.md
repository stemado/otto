# Workflow JSON Schema Design

**Date:** 2026-02-19
**Status:** Approved

## Problem

Browser-scout generates session histories (action logs, scout data, network events) but has no standardized, portable format for representing a replayable workflow. The existing `/export-workflow` command outputs Python scripts, which are one-shot and not machine-parseable. A JSON schema would enable:

1. A Python executor to replay workflows without Claude in the loop
2. Workflow storage, versioning, and sharing
3. Future multi-runtime support (C# backend)

## Prior Art

The `BotasaurusDesktopRunner` and `BotasaurusExecutionService` projects (in `BrowserAutomationServices`) implemented an earlier prototype with:
- Recorded workflow JSON files with step arrays
- A `BotasaurusWorkflowExecutor` with a registry of 11 step type executors
- Variable resolution, iframe context management, fallback selectors
- Per-step error handling policies

Key lessons from that prototype:
- **Keep:** Per-step error handling, variable references, iframe context as step metadata
- **Drop:** Duplicate variable resolution systems, framework detection per action, hardcoded network-idle sleeps
- **Fix:** Credential handling (was plaintext), recording noise (duplicate navs, accidental clicks)

## Decision

**Flat step list with hybrid dynamics handling:**
- Core actions (click, type, navigate) carry declarative metadata (frame_context, shadow_pierce)
- Lifecycle actions (downloads, network waits) are explicit step types
- Variables with `${VAR}` reference syntax, fail-fast resolution
- Single selector per step (no fallback arrays) — YAGNI
- Primary consumer: Python executor using botasaurus-driver

## Schema Definition

### Workflow Envelope

```json
{
  "schema_version": "1.0",
  "name": "string — slugified workflow identifier",
  "description": "string — human-readable purpose",
  "created": "string — ISO 8601 timestamp",
  "source": {
    "tool": "string — e.g. 'browser-scout'",
    "session_id": "string — originating session"
  },
  "variables": {},
  "settings": {},
  "steps": []
}
```

### Variables Section

Variables are declared at the top level and referenced in step values via `${VAR_NAME}`.

```json
{
  "variables": {
    "USERNAME": {
      "type": "credential | string | url",
      "default": "string — placeholder value",
      "description": "string — what this variable is for"
    }
  }
}
```

**Variable types:**
- `credential` — executor masks in logs, never persists in output
- `string` — general-purpose text
- `url` — validated as URL format

**Resolution rules:**
- Variables are resolved before execution starts (fail-fast)
- Unresolved variables cause an immediate error, not a runtime surprise
- `${VAR}` syntax in any string field triggers resolution
- Nested references are not supported (no `${${INNER}}`)

### Settings Section

```json
{
  "settings": {
    "headless": false,
    "default_timeout_ms": 30000,
    "step_delay_ms": 500,
    "on_error": "stop | continue | retry"
  }
}
```

- `headless` — browser visibility mode (default: `false`)
- `default_timeout_ms` — per-step timeout unless overridden (default: `30000`)
- `step_delay_ms` — pause between steps (default: `500`)
- `on_error` — global error policy, overridable per step (default: `"stop"`)

### Step Schema

Every step has common fields plus action-specific fields.

#### Common Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `order` | int | yes | Execution sequence (1-indexed) |
| `name` | string | yes | Human-readable description |
| `action` | string | yes | Action type (see below) |
| `on_error` | string | no | Override global error policy |
| `timeout_ms` | int | no | Override global timeout |

#### Action Types

##### `navigate`
Navigate to a URL.

| Field | Type | Required |
|-------|------|----------|
| `value` | string (URL) | yes |
| `wait_for_load` | bool | no (default: true) |

##### `click`
Click an element.

| Field | Type | Required |
|-------|------|----------|
| `selector` | string (CSS) | yes |
| `frame_context` | string | no |
| `shadow_pierce` | bool | no (default: false) |

##### `type`
Type text into an input field.

| Field | Type | Required |
|-------|------|----------|
| `selector` | string (CSS) | yes |
| `value` | string | yes |
| `frame_context` | string | no |
| `clear_first` | bool | no (default: false) |

##### `select`
Select an option from a dropdown.

| Field | Type | Required |
|-------|------|----------|
| `selector` | string (CSS) | yes |
| `value` | string | yes |
| `frame_context` | string | no |

##### `scroll`
Scroll the page.

| Field | Type | Required |
|-------|------|----------|
| `value` | string (pixels) | no (default: "500") |

##### `wait`
Wait for a condition. Either a selector to appear or a fixed time.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `selector` | string (CSS) | no | Wait for element to appear |
| `value` | string (ms) | no | Fixed time wait |
| `frame_context` | string | no | For selector waits |

One of `selector` or `value` should be provided. If `selector` is given, waits for the element. If `value` is given, sleeps for that duration. If both, waits for element with timeout.

##### `wait_for_download`
Wait for a file download to complete. Placed after the step that triggers the download.

| Field | Type | Required |
|-------|------|----------|
| `filename_pattern` | string (glob) | no |
| `timeout_ms` | int | no (default: 30000) |
| `download_dir` | string (path) | no |

##### `wait_for_response`
Wait for a specific network response. Used when an action triggers an AJAX call whose completion matters.

| Field | Type | Required |
|-------|------|----------|
| `url_pattern` | string (regex) | yes |
| `method` | string | no (default: any) |
| `timeout_ms` | int | no (default: 30000) |

##### `press_key`
Press a keyboard key.

| Field | Type | Required |
|-------|------|----------|
| `value` | string (key name) | yes |

##### `hover`
Hover over an element.

| Field | Type | Required |
|-------|------|----------|
| `selector` | string (CSS) | yes |
| `frame_context` | string | no |

##### `clear`
Clear an input field.

| Field | Type | Required |
|-------|------|----------|
| `selector` | string (CSS) | yes |
| `frame_context` | string | no |

### Dynamic Features Handling

#### Iframe Context (Declarative)

Iframe context is a metadata field on steps, not a separate step type. The `frame_context` field contains the CSS selector of the iframe containing the target element. For nested iframes, use `>>>` syntax: `"iframe#outer >>> iframe#inner"`.

The executor is responsible for switching to the correct iframe context before executing the action, and returning to the main content afterward (context manager pattern from the old `IframeContextManager`).

#### Shadow DOM (Declarative)

Shadow DOM piercing is handled via `shadow_pierce: true` on click/type/select steps. The executor uses the `>>>` pierce syntax when locating elements. This is a selector-level concern, not a workflow step.

#### Downloads (Explicit Step)

Downloads are represented as `wait_for_download` steps placed after the action that triggers the download. The executor uses filesystem polling (snapshot-before, diff-after) to detect new files.

#### Network Waits (Explicit Step)

AJAX-dependent workflows use `wait_for_response` steps to wait for specific network calls. This replaces the old hardcoded `asyncio.sleep(2.0)` for "network idle" — instead, we wait for the specific response that matters.

## Complete Example: ADP Report Download

```json
{
  "schema_version": "1.0",
  "name": "adp-report-download",
  "description": "Log into ADP WFN and download the Unum LTD FMLA report",
  "created": "2026-02-19T14:30:00Z",
  "source": {
    "tool": "browser-scout",
    "session_id": "abc123"
  },
  "variables": {
    "USERNAME": {
      "type": "credential",
      "default": "your_username",
      "description": "ADP login username"
    },
    "PASSWORD": {
      "type": "credential",
      "default": "your_password",
      "description": "ADP login password"
    },
    "REPORT_NAME": {
      "type": "string",
      "default": "Unum_LTD_FMLA_Report",
      "description": "Name of the report to download"
    }
  },
  "settings": {
    "headless": false,
    "default_timeout_ms": 30000,
    "step_delay_ms": 500,
    "on_error": "stop"
  },
  "steps": [
    {
      "order": 1,
      "name": "Navigate to ADP sign-in",
      "action": "navigate",
      "value": "https://online.adp.com/signin/v1/?APPID=WFNPortal&productId=80e309c3-7085-bae1-e053-3505430b5495&returnURL=https://workforcenow.adp.com/"
    },
    {
      "order": 2,
      "name": "Enter username",
      "action": "type",
      "selector": "#login-form_username",
      "value": "${USERNAME}",
      "clear_first": true
    },
    {
      "order": 3,
      "name": "Click Next button",
      "action": "click",
      "selector": "[data-testid='verifUseridBtn']"
    },
    {
      "order": 4,
      "name": "Enter password",
      "action": "type",
      "selector": "#login-form_password",
      "value": "${PASSWORD}",
      "clear_first": true
    },
    {
      "order": 5,
      "name": "Click Sign In",
      "action": "click",
      "selector": "#signBtn"
    },
    {
      "order": 6,
      "name": "Wait for WFN dashboard to load",
      "action": "wait",
      "selector": "#shellNavComponent",
      "timeout_ms": 15000
    },
    {
      "order": 7,
      "name": "Navigate to Custom Reports",
      "action": "navigate",
      "value": "https://workforcenow.adp.com/theme/admin.html#/Reports/ReportsTabCustomReportsCategoryAllReports"
    },
    {
      "order": 8,
      "name": "Click report link",
      "action": "click",
      "selector": "[aria-label='${REPORT_NAME}']",
      "frame_context": "iframe#adprIframe",
      "timeout_ms": 15000
    },
    {
      "order": 9,
      "name": "Wait for report to download",
      "action": "wait_for_download",
      "timeout_ms": 60000,
      "filename_pattern": "*.csv"
    }
  ]
}
```

## Scope

### Phase 1 (This Design)
- Define the JSON schema
- Update `/export-workflow` to output this JSON format (in addition to Python scripts)
- Add a Pydantic model in browser-scout for validation

### Phase 2 (Future)
- Python executor that consumes this JSON and replays via botasaurus-driver
- JSON Schema file (`.schema.json`) for IDE validation
- Phase grouping extension (optional `phase` field on steps)
- C# executor for backend consumption

## Non-Goals
- Fallback selectors (re-scout if selectors break)
- Conditional branching (if/else in workflows)
- Loop constructs (iterate over lists)
- Cross-workflow composition (import/include)
