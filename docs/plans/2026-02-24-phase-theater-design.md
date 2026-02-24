# Phase Theater — Stakeholder Demo Page

**Date**: 2026-02-24
**Status**: Design
**Type**: Single-file static HTML (zero dependencies)
**Output**: `docs/phase-theater.html`

## Purpose

An animated, interactive demo page that walks stakeholders through Otto's four-phase journey from Claude Code plugin to autonomous platform. Designed to be visually engaging ("fun informative demonstration") and self-explanatory — a stakeholder can watch it auto-play or click through at their own pace.

## Reference Materials

- **Visual style**: `docs/showcase.html` — dark GitHub-style theme, `AnimationEngine` class, browser chrome simulation, tool-box components, typewriter effects
- **Content source**: `docs/otto-strategic-overview.jsx` — 4 phases, architecture layers, solved concerns

## Interaction Model

- **Auto-play**: On load, phases play sequentially (I → II → III → IV → Architecture capstone). Each phase ~15-20 seconds.
- **Timeline controls**: Click any phase node to jump directly. Current phase demo restarts from its beginning.
- **Pause/Resume**: Click the active phase node to pause/resume.
- **Replay**: Button appears after full sequence completes (same pattern as showcase).

## Page Sections

### 1. Header

Centered, same visual vocabulary as showcase.

```
Otto.
From plugin to platform — the four-phase journey.

Otto starts as a Claude Code plugin that automates enterprise portals.
Here's how it becomes the API layer legacy systems never built.
```

Small "← Back to showcase" link in top-left corner.

### 2. Phase Timeline Bar

Horizontal bar with 4 connected nodes. Each node:
- Roman numeral (I–IV)
- Title ("Plugin", "Workflows", "Hosted API", "Adaptive Intelligence")
- Status badge: green "Active" / cyan "Next" / muted "Future"
- Glow effect on currently-playing phase
- Thin animated progress line fills between nodes during auto-play

Clicking a node jumps to that phase. Completed phases show a subtle checkmark.

### 3. The Stage — Per-Phase Animated Demos

Large stage area below the timeline. Swaps content for each phase.

#### Phase I — "Plugin" (Claude Code MCP Server)

Reuses showcase's browser chrome + response area pattern directly.

**Simulated browser** starts at `vendor-portal.example.com/login` showing a login form.

**Response area** plays the following tool-call sequence:
1. `scout_page_tool` → reports page title, iframe (vendor SSO), element counts
2. `fill_secret` → env_var: "PORTAL_PASSWORD", chars_typed: 16, "Password value: never in conversation"
3. Browser transitions to `vendor-portal.example.com/dashboard` showing a portal dashboard with nav tabs and a data table
4. `execute_action_tool` → click "Export Report"
5. `monitor_network` → captures GET `/api/reports/export.csv` — 200 OK, 48 KB
6. `/export-workflow vendor-report` → file tree: `run.py`, `workflow.json`, `requirements.txt`, `.env.example`
7. Browser transitions to show the exported file tree

**Closing line**: "The API that should have existed all along."

**Audience label**: "Internal" (muted badge)
**Validates**: "Reliable automation against portals with anti-bot detection"

#### Phase II — "Workflows" (Stored & Scheduled Automation)

**Simulated dashboard UI** replaces the browser chrome:
- Header: "Otto Workflow Engine" with a status indicator
- Workflow table with columns: Name, Schedule, Last Run, Status

**Animated sequence**:
1. Table appears with 3 workflows:
   - "benefits-enrollment" — `0 6 * * 1` (Mon 6am) — "2h ago" — green "OK"
   - "vendor-invoices" — `0 8 * * *` (Daily 8am) — "Running..." — cyan spinner
   - "compliance-audit" — `0 0 1 * *` (1st of month) — "3d ago" — green "OK"
2. "vendor-invoices" transitions: "Running..." → green checkmark "Complete — 142 records"
3. Sleep, then "benefits-enrollment" triggers a new run: "Scheduled" → "Running..."
4. Fails: status turns red "Failed — selector #export-btn not found"
5. Self-healing kicks in — response area shows:
   - "Failure detected: selector `#export-btn` missing"
   - `claude_diagnose` → "Portal updated export button: `#export-btn` → `.btn-export-csv`"
   - "Auto-repair applied. Retrying..."
6. Status transitions: red "Failed" → cyan "Retrying" → green "Complete — 847 records"

**Closing line**: "Runs unattended. Heals itself."

**Audience label**: "Internal → External"
**Validates**: "Unattended execution reliability and failure recovery"

#### Phase III — "Hosted API" (Published REST Endpoints)

**Split-panel API console** replaces the stage:
- Left panel: "Request" — simulated terminal/code block
- Right panel: "Response" — JSON output area

**Animated sequence**:
1. Left panel typewriter types a curl command:
   ```
   $ curl -X POST https://api.otto.dev/v1/benefits/enrollment \
       -H "Authorization: Bearer $OTTO_TOKEN" \
       -H "Content-Type: application/json" \
       -d '{"period": "2026-02", "format": "csv"}'
   ```
2. Small annotation fades in below: "The caller never knows a browser was involved."
3. Right panel — JSON response appears line-by-line:
   ```json
   {
     "status": "complete",
     "workflow": "benefits-enrollment",
     "records": 847,
     "format": "csv",
     "download_url": "https://api.otto.dev/v1/dl/abc123",
     "duration_ms": 12400,
     "browser_used": true,
     "billing": { "credits": 1, "tier": "standard" }
   }
   ```
4. The `"browser_used": true` line gets a brief highlight with annotation: "Transparent to the consumer"

**Closing line**: "The Plaid model for every legacy system."

**Audience label**: "Internal → Gradual External"
**Validates**: "Enterprise-grade API synthesis at scale"

#### Phase IV — "Adaptive Intelligence" (Claude API — Proactive Change Detection)

**Split-view portal health monitor**:
- Left panel: "Expected" — wireframe/schematic of a portal page (simplified boxes representing form fields, buttons, nav)
- Right panel: "Actual" — same layout but with differences highlighted (a button moved, a field renamed)

**Animated sequence**:
1. Both panels appear side-by-side showing the portal schematic
2. Right panel "flickers" — 2-3 elements shift position / change labels (animated with CSS transforms):
   - Login button changes from `#btn-login` to `.auth-submit`
   - A form field label changes
   - A nav item is added
3. Diff highlights appear (orange borders around changed elements)
4. Response area below shows Claude's analysis:
   - "Scheduled health scan complete — 3 changes detected"
   - "1. Login button: `#btn-login` → `.auth-submit`" — Classification: **Cosmetic** — Action: Auto-repair applied
   - "2. Form label: 'Employee ID' → 'Worker ID'" — Classification: **Cosmetic** — Action: Auto-repair applied
   - "3. New nav item: 'API Access'" — Classification: **Structural** — Action: Flagged for human review
5. Autonomy spectrum bar animates: green section (auto-repair) widens, yellow section (propose+approve) stays, red section (human-only) narrows
6. Counter: "Portal integrations monitored: 247 — Auto-healed this week: 31"

**Closing line**: "1,000 portals ≠ 1,000 engineers."

**Audience label**: "Platform-Wide"
**Validates**: "Operational scalability without proportional human intervention"

### 4. Architecture Stack (Capstone)

After Phase IV completes, section scrolls into view. Architecture layers animate in bottom-to-top, each sliding up and connecting to the layer above:

| Layer | Color | Items |
|-------|-------|-------|
| Browser Runtime | `#8B5CF6` (purple) | Headless Chromium Pool, Session Management, Anti-Detection Engine, Portal Connectors |
| Security Boundary | `#10B981` (green) | Azure Key Vault, Per-Tenant Isolation, Credential Injection, Audit Logging |
| PII Redaction Middleware | `#EF4444` (red) | OCR + Pattern Matching, Semantic Page Descriptions, Image Redaction, Local LLM Processing |
| Orchestration | `#3B82F6` (blue) | Workflow Engine, Queue Management, Scheduling, Self-Healing (Claude) |
| Otto API Layer | `#F59E0B` (orange) | REST Endpoints, Auth & Rate Limiting, Schema Contracts, Billing/Metering |
| Client Systems | `#94A3B8` (grey) | ERP, HRIS, Payroll Engine, Custom Apps |

Each layer is a horizontal bar. Items listed inline. Hover shows one-line description. No deep-dive — just the visual stack showing how the pieces connect.

### 5. CTA

Same pattern as showcase:
```
$ /plugin marketplace add stemado/otto-marketplace
$ /plugin install otto@otto-marketplace
```
Links to Getting Started Guide and GitHub.

## Technical Approach

### Reused from showcase.html
- `AnimationEngine` class (verbatim — typewriter, fadeIn, fadeOut, browserUpdate, appendLine, highlight, clear, sleep)
- CSS variable system (`--bg`, `--surface`, `--border`, `--text`, `--muted`, `--green`, `--cyan`, `--yellow`, `--red`, `--orange`)
- Font stack: `'Cascadia Code', 'Fira Code', 'SF Mono', 'Consolas', monospace`
- Component patterns: `.browser-chrome`, `.tool-box`, `.response-line`, `.sim-*` elements
- Dot grid background, section dividers, utility classes

### New components
- **Phase timeline bar** — flexbox row, 4 nodes connected by lines, animated progress fill
- **Dashboard UI** (Phase II) — simulated workflow table with status transitions
- **API console** (Phase III) — split-panel with terminal left / JSON right
- **Health monitor** (Phase IV) — split-panel wireframe comparison with diff highlights
- **Architecture stack** — stacked horizontal bars with staggered slide-in animation
- **Phase stage controller** — JS object managing which phase is active, auto-play sequencing, pause/resume state

### New AnimationEngine step types
Extend the existing engine with:
- `dashboardUpdate` — swap dashboard table row content with transition
- `jsonAppend` — append JSON lines with syntax highlighting
- `diffHighlight` — add orange border highlights to elements in the health monitor
- `layerSlideIn` — slide an architecture layer up from below

### State management
Simple object, no framework:
```js
const state = {
  currentPhase: 0,      // 0-3
  isPlaying: true,
  isPaused: false,
  phaseComplete: [false, false, false, false],
};
```

### Estimated size
~2,500-3,000 lines of HTML/CSS/JS (showcase is ~1,400 lines). The additional scenes and UI components account for the increase.
