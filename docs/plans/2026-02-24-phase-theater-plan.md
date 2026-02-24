# Phase Theater Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a single-file animated HTML page (`docs/phase-theater.html`) that demos Otto's 4-phase journey for stakeholders, using the showcase.html visual language.

**Architecture:** Single-file static HTML with embedded CSS and JS. Reuses the `AnimationEngine` class and CSS variable system from `docs/showcase.html`. New components for timeline bar, dashboard UI, API console, health monitor, and architecture stack. Phase controller manages auto-play sequencing with click-to-jump controls.

**Tech Stack:** Vanilla HTML/CSS/JS, zero dependencies. Same monospace dark theme as showcase.

**Design doc:** `docs/plans/2026-02-24-phase-theater-design.md`

---

## Task 1: Scaffold — HTML skeleton + shared CSS

Create `docs/phase-theater.html` with the foundational structure. This task produces a page you can open in a browser that shows the header, empty timeline, empty stage, and CTA — all correctly styled but with no animations.

**Files:**
- Create: `docs/phase-theater.html`

**Step 1: Create the HTML file with complete CSS**

Write the full file with these sections (reference `docs/showcase.html` lines 7-646 for exact CSS variable values, font stack, and utility classes):

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Otto — From Plugin to Platform</title>
<style>
  /* === REUSED FROM SHOWCASE === */
  /* Copy these verbatim from showcase.html:
     - Reset (line 8)
     - :root variables (lines 10-21)
     - html/body base styles (lines 23-38)
     - .page layout (lines 41-45)
     - Section separators: .section, .section-divider, .section-header, .section-subtitle (lines 48-66)
     - Tool box components: .tool-box, .tool-box-header, .tool-row, .tool-callout (lines 207-235)
     - Browser chrome: .browser-chrome through .browser-content (lines 125-170)
     - Response area: .response-area, .response-line (lines 173-204)
     - Simulated elements: .sim-form through .sim-file-tree (lines 471-581)
     - Utility classes: .ok, .str, .cyan, .yellow, .red, .dim, .orange, .redacted, .hidden (lines 586-601)
     - Keyframes: fadeIn, typeLine, blink (lines 606-613, 273-276)
  */

  /* === NEW: Back link === */
  .back-link { ... }

  /* === NEW: Phase Timeline === */
  .timeline { ... }
  .timeline-track { ... }
  .timeline-progress { ... }
  .timeline-node { ... }
  .timeline-node.active { ... }
  .timeline-node.completed { ... }
  .timeline-node .node-number { ... }
  .timeline-node .node-title { ... }
  .timeline-node .node-badge { ... }

  /* === NEW: Stage Container === */
  .stage { ... }
  .stage-meta { ... } /* audience + validates labels */

  /* === NEW: Phase II Dashboard === */
  .dash-header { ... }
  .dash-table { ... }
  .dash-status { ... }
  .dash-status.running { ... }
  .dash-status.ok { ... }
  .dash-status.failed { ... }
  .dash-status.retrying { ... }

  /* === NEW: Phase III API Console === */
  .api-console { ... }
  .api-panel { ... }
  .api-panel-header { ... }
  .json-line { ... }
  .json-key { ... }
  .json-string { ... }
  .json-number { ... }
  .json-bool { ... }

  /* === NEW: Phase IV Health Monitor === */
  .health-monitor { ... }
  .health-panel { ... }
  .health-panel-header { ... }
  .wireframe { ... }
  .wireframe-element { ... }
  .wireframe-element.changed { ... }
  .autonomy-bar { ... }
  .autonomy-segment { ... }

  /* === NEW: Architecture Stack === */
  .arch-stack { ... }
  .arch-layer { ... }
  .arch-layer-name { ... }
  .arch-layer-items { ... }

  /* === NEW: Phase closing line === */
  .phase-closing { ... }

  /* === RESPONSIVE === */
  @media (max-width: 768px) { ... }
</style>
</head>
<body>
<div class="page">
  <!-- Back link -->
  <a class="back-link" href="showcase.html">&larr; Showcase</a>

  <!-- SECTION 1: Header -->
  <header class="header">...</header>

  <!-- SECTION 2: Timeline -->
  <div class="timeline" id="timeline">...</div>

  <!-- SECTION 3: Stage -->
  <div class="stage" id="stage">
    <!-- Content swapped by JS per phase -->
  </div>

  <!-- Response area (shared across phases) -->
  <div class="response-area" id="phase-response"></div>

  <!-- SECTION 4: Architecture Stack -->
  <div class="section" id="architecture">...</div>

  <!-- SECTION 5: CTA -->
  <div class="section" id="get-started">...</div>
</div>

<script>
  // JS goes here in later tasks
</script>
</body>
</html>
```

The CSS must include all showcase-reused styles AND all new component styles listed above. Write the complete CSS — do not leave `{ ... }` placeholders. Reference the design doc for colors, layout, and component specifications.

**Key CSS details for new components:**

**Timeline bar:**
- `display: flex; align-items: center; justify-content: space-between;` on `.timeline`
- Each `.timeline-node` is a flex column (number on top, title below, badge below that)
- Connecting lines between nodes via `.timeline-track` (absolute-positioned thin line behind nodes)
- `.timeline-progress` overlays the track with `var(--orange)` color, width animated via JS
- Active node gets `box-shadow: 0 0 20px rgba(240, 136, 62, 0.3)` and brighter border
- Node badges: green bg for "Active", cyan bg for "Next", muted bg for "Future"

**Stage:**
- `min-height: 400px` container with `position: relative`
- Content is swapped by JS — each phase injects its own HTML
- `opacity` transitions on swap (fade out old, fade in new)

**Dashboard (Phase II):**
- Reuse `.sim-table` pattern from showcase but add `.dash-status` badges
- Status badges: green "OK", cyan animated "Running...", red "Failed", cyan "Retrying"
- Running status has a CSS animation (subtle pulse or spinner)

**API Console (Phase III):**
- Two-panel flexbox layout, 50/50 split
- Left panel: dark bg, monospace, simulated terminal
- Right panel: dark bg, JSON with syntax highlighting via CSS classes
- `.json-key` = cyan, `.json-string` = green, `.json-number` = orange, `.json-bool` = yellow

**Health Monitor (Phase IV):**
- Two-panel layout, "Expected" vs "Actual"
- Wireframe elements are simple CSS boxes (borders, labels) representing form fields, buttons, nav
- `.changed` class adds orange border + subtle glow
- Autonomy spectrum bar: horizontal bar divided into 3 colored segments (green/yellow/red) with CSS width transitions

**Architecture stack:**
- Vertical stack of horizontal bars, each with a left-side color accent
- Each bar has `transform: translateY(30px); opacity: 0` initially, animated in with staggered delays
- Layer colors from design doc table

**Step 2: Verify the scaffold renders**

Open `docs/phase-theater.html` in a browser. You should see:
- Dark background with dot grid
- "Otto." header with tagline
- 4 timeline nodes (I through IV) connected by a horizontal line
- An empty stage area
- Architecture section (hidden/empty initially)
- CTA with install commands

No animations yet — just the static layout.

**Step 3: Commit**

```bash
git add -f docs/phase-theater.html
git commit -m "feat: scaffold phase-theater page with HTML skeleton and CSS"
```

---

## Task 2: AnimationEngine + Phase Controller

Add the JavaScript foundation: the `AnimationEngine` class (copied from showcase) plus the new `PhaseController` that manages auto-play, phase switching, and timeline updates.

**Files:**
- Modify: `docs/phase-theater.html` (add JS in `<script>` block)

**Step 1: Copy AnimationEngine from showcase**

Copy the `AnimationEngine` class verbatim from `docs/showcase.html` lines 914-1096 into the `<script>` block. This gives you:
- `typewriter`, `fadeIn`, `fadeOut`, `browserUpdate`, `appendLine`, `highlight`, `clear`, `sleep`
- Abort controller support for stopping scenes mid-play

**Step 2: Extend AnimationEngine with new step types**

Add these methods to the class and register them in the `exec()` switch:

```javascript
// In exec() switch, add:
case 'stageSwap':      return this.stageSwap(step);
case 'dashboardUpdate': return this.dashboardUpdate(step);
case 'jsonAppend':      return this.jsonAppend(step);
case 'diffHighlight':   return this.diffHighlight(step);
case 'layerSlideIn':    return this.layerSlideIn(step);
case 'counterUpdate':   return this.counterUpdate(step);
```

**`stageSwap({ html, fadeMs = 250 })`** — Fade out `#stage`, swap innerHTML, fade in. Similar to `browserUpdate` but targets the stage container.

**`dashboardUpdate({ rowSelector, statusHtml, statusClass })`** — Find a table row by selector, update its status cell content and class with a brief flash transition.

**`jsonAppend({ target, line, delay = 60 })`** — Append a syntax-highlighted JSON line to the target. Apply CSS classes based on content (keys = cyan, strings = green, numbers = orange, booleans = yellow).

**`diffHighlight({ target, className = 'changed', duration = 0 })`** — Add the `changed` class to an element. If duration > 0, remove after duration.

**`layerSlideIn({ target, delay = 0 })`** — After delay, transition element from `translateY(30px) opacity:0` to `translateY(0) opacity:1`.

**`counterUpdate({ target, text })`** — Update text content of target element with a brief fade transition.

**Step 3: Write the PhaseController**

```javascript
const PhaseController = {
  engine: new AnimationEngine(),
  currentPhase: -1,
  isPlaying: false,
  isPaused: false,
  phases: [], // populated in Task 3+

  async playAll() {
    this.isPlaying = true;
    this.isPaused = false;
    for (let i = 0; i < this.phases.length; i++) {
      if (!this.isPlaying) return;
      await this.playPhase(i);
      if (!this.isPlaying) return;
      // Brief pause between phases
      await this.engine.sleep(1500);
    }
    // Play architecture capstone
    await this.playArchitecture();
    this.isPlaying = false;
    this.showReplay();
  },

  async playPhase(index) {
    this.currentPhase = index;
    this.updateTimeline();

    // Clear stage and response area
    document.getElementById('stage').innerHTML = '';
    document.getElementById('phase-response').innerHTML = '';

    const phase = this.phases[index];

    // Inject phase stage HTML
    document.getElementById('stage').innerHTML = phase.stageHtml;
    document.getElementById('stage').style.opacity = '0';
    // Force reflow
    document.getElementById('stage').offsetHeight;
    document.getElementById('stage').style.transition = 'opacity 0.3s ease';
    document.getElementById('stage').style.opacity = '1';

    // Show meta info (audience, validates)
    // ...

    // Play the phase scene
    await this.engine.play(phase.scene, {});

    // Mark phase complete
    this.markComplete(index);
  },

  jumpToPhase(index) {
    this.engine.stop();
    this.isPlaying = true;
    this.isPaused = false;
    this.playPhase(index).then(() => {
      // After jumping, don't auto-continue
      this.isPlaying = false;
      this.showReplay();
    });
  },

  togglePause() {
    if (this.isPaused) {
      this.isPaused = false;
      // Resume is complex with the current engine — simplest approach:
      // just replay from current phase
    } else {
      this.isPaused = true;
      this.engine.stop();
    }
    this.updateTimeline();
  },

  updateTimeline() {
    // Update node classes: active, completed, future
    // Update progress bar width
    document.querySelectorAll('.timeline-node').forEach((node, i) => {
      node.classList.toggle('active', i === this.currentPhase);
      node.classList.toggle('completed', i < this.currentPhase);
    });
    // Progress bar: width = (currentPhase / 3) * 100%
    const progress = document.querySelector('.timeline-progress');
    if (progress) {
      progress.style.width = `${(this.currentPhase / (this.phases.length - 1)) * 100}%`;
    }
  },

  markComplete(index) {
    const node = document.querySelectorAll('.timeline-node')[index];
    if (node) node.classList.add('completed');
  },

  async playArchitecture() {
    // Reveal architecture section, animate layers bottom-to-top
    const section = document.getElementById('architecture');
    section.classList.remove('hidden');
    const layers = section.querySelectorAll('.arch-layer');
    // Animate from last (bottom) to first (top)
    for (let i = layers.length - 1; i >= 0; i--) {
      await this.engine.sleep(200);
      layers[i].style.transition = 'transform 0.5s ease, opacity 0.5s ease';
      layers[i].style.transform = 'translateY(0)';
      layers[i].style.opacity = '1';
    }
  },

  showReplay() {
    const btn = document.getElementById('replay-btn');
    if (btn) btn.classList.add('visible');
  },
};
```

**Step 4: Wire timeline click handlers and replay button**

```javascript
document.querySelectorAll('.timeline-node').forEach((node, i) => {
  node.addEventListener('click', () => PhaseController.jumpToPhase(i));
});

document.getElementById('replay-btn').addEventListener('click', () => {
  document.getElementById('replay-btn').classList.remove('visible');
  PhaseController.playAll();
});
```

**Step 5: Verify the controller works**

Add a temporary test: `PhaseController.phases = [{ stageHtml: '<p>Phase I test</p>', scene: [{ type: 'sleep', ms: 1000 }] }];`

Open the page, run `PhaseController.playAll()` in browser console. The stage should show "Phase I test", timeline node I should light up, and after 1 second the replay button should appear.

**Step 6: Commit**

```bash
git add -f docs/phase-theater.html
git commit -m "feat: add AnimationEngine and PhaseController to phase-theater"
```

---

## Task 3: Phase I Scene — "Plugin"

Build the Phase I animated demo. This reuses showcase patterns most heavily.

**Files:**
- Modify: `docs/phase-theater.html`

**Step 1: Define Phase I stage HTML and scene**

Add the following to the `<script>` block, before `PhaseController.playAll()`:

**Stage HTML** — login form inside browser chrome (same markup as showcase's `loginPageHTML`, `dashboardHTML`, `fileTreeHTML`). Copy these HTML fragments from showcase lines 1105-1138 and adapt:
- URL starts at `vendor-portal.example.com/login`
- Login form with Email + Password fields
- Dashboard with portal header, nav tabs, data table
- File tree with exported workflow files

**Scene array** — model after showcase's `heroScene` (lines 1159-1203). The scene should:
1. `appendLine` — "I'll scout the login page first."
2. `appendLine` — `scout_page_tool` tool-box (page title, iframes, elements)
3. `appendLine` — "Login form is inside an iframe. Filling credentials securely."
4. `appendLine` — `fill_secret` tool-box (env_var, chars_typed, warning)
5. `browserUpdate` — swap to dashboard (URL + HTML)
6. `appendLine` — `execute_action_tool` tool-box (click "Export Report")
7. `appendLine` — `monitor_network` tool-box (GET, 200 OK, 48 KB)
8. `appendLine` — `/export-workflow` tool-box (file tree)
9. `browserUpdate` — swap to file tree view
10. `appendLine` — closing line: "The API that should have existed all along."

Use the `toolBox()` helper function from showcase (lines 1141-1156) — copy it verbatim.

**Register phase:**
```javascript
PhaseController.phases[0] = {
  stageHtml: phaseIStageHtml,  // browser chrome with login page
  scene: phaseIScene,
  title: 'Plugin',
  subtitle: 'Claude Code MCP Server',
  audience: 'Internal',
  validates: 'Reliable automation against portals with anti-bot detection',
};
```

**Step 2: Test Phase I in isolation**

Open the page. Run `PhaseController.jumpToPhase(0)` in console. The entire Phase I demo should play: browser chrome shows login page, tool calls animate in the response area, browser transitions to dashboard then file tree, closing line appears.

**Step 3: Commit**

```bash
git add -f docs/phase-theater.html
git commit -m "feat: add Phase I Plugin demo scene to phase-theater"
```

---

## Task 4: Phase II Scene — "Workflows"

Build the workflow dashboard demo with self-healing narrative.

**Files:**
- Modify: `docs/phase-theater.html`

**Step 1: Define Phase II stage HTML**

Create the dashboard HTML:
- Header bar: "Otto Workflow Engine" with green status dot
- Table with columns: Workflow, Schedule, Last Run, Status
- 3 rows with initial data (benefits-enrollment, vendor-invoices, compliance-audit)
- Each status cell has an `id` for targeted updates (e.g., `id="status-vendor"`)

**Step 2: Define Phase II scene**

The scene uses a mix of `dashboardUpdate` and `appendLine` steps:

1. `sleep(800)` — let dashboard render
2. `dashboardUpdate` — vendor-invoices: "Running..." → "Complete — 142 records" (green)
3. `sleep(1200)`
4. `dashboardUpdate` — benefits-enrollment: "2h ago" → "Running..." (cyan)
5. `sleep(1500)`
6. `dashboardUpdate` — benefits-enrollment: "Running..." → "Failed — selector #export-btn not found" (red)
7. `sleep(800)`
8. `appendLine` — "Failure detected: selector `#export-btn` missing"
9. `appendLine` — tool-box `claude_diagnose`: "Portal updated export button: `#export-btn` → `.btn-export-csv`"
10. `appendLine` — "Auto-repair applied. Retrying..."
11. `dashboardUpdate` — benefits-enrollment: "Failed..." → "Retrying..." (cyan)
12. `sleep(1500)`
13. `dashboardUpdate` — benefits-enrollment: "Retrying..." → "Complete — 847 records" (green)
14. `appendLine` — closing line: "Runs unattended. Heals itself."

**Step 3: Register phase and test**

```javascript
PhaseController.phases[1] = {
  stageHtml: phaseIIStageHtml,
  scene: phaseIIScene,
  title: 'Workflows',
  subtitle: 'Stored & Scheduled Automation',
  audience: 'Internal → External',
  validates: 'Unattended execution reliability and failure recovery',
};
```

Test: `PhaseController.jumpToPhase(1)` in console. Dashboard should appear, statuses should transition through the sequence, self-healing narrative should play in response area.

**Step 4: Commit**

```bash
git add -f docs/phase-theater.html
git commit -m "feat: add Phase II Workflows demo scene to phase-theater"
```

---

## Task 5: Phase III Scene — "Hosted API"

Build the API console demo with curl request and JSON response.

**Files:**
- Modify: `docs/phase-theater.html`

**Step 1: Define Phase III stage HTML**

Two-panel layout:
```html
<div class="api-console">
  <div class="api-panel">
    <div class="api-panel-header">Request</div>
    <div class="api-terminal" id="api-request">
      <span class="dim">$</span> <span id="api-curl"></span><span class="cursor"></span>
    </div>
  </div>
  <div class="api-panel">
    <div class="api-panel-header">Response</div>
    <div class="api-json" id="api-response"></div>
  </div>
</div>
```

**Step 2: Define Phase III scene**

1. `typewriter` on `#api-curl` — types the curl command character by character (slower charDelay ~25ms for dramatic effect)
2. `sleep(600)`
3. `appendLine` below the console — "The caller never knows a browser was involved."
4. `jsonAppend` to `#api-response` — each line of JSON response:
   - `{`
   - `  "status": "complete",`
   - `  "workflow": "benefits-enrollment",`
   - `  "records": 847,`
   - `  "format": "csv",`
   - `  "download_url": "https://api.otto.dev/v1/dl/abc123",`
   - `  "duration_ms": 12400,`
   - `  "browser_used": true,`
   - `  "billing": { "credits": 1, "tier": "standard" }`
   - `}`
5. `highlight` on the `browser_used` line — brief orange glow
6. `appendLine` — annotation: "Transparent to the consumer"
7. `appendLine` — closing line: "The Plaid model for every legacy system."

**Step 3: Register phase and test**

```javascript
PhaseController.phases[2] = {
  stageHtml: phaseIIIStageHtml,
  scene: phaseIIIScene,
  title: 'Hosted API',
  subtitle: 'Published REST Endpoints',
  audience: 'Internal → Gradual External',
  validates: 'Enterprise-grade API synthesis at scale',
};
```

Test: `PhaseController.jumpToPhase(2)` in console. Curl command should type out, JSON response should appear line by line with syntax colors, `browser_used` should highlight.

**Step 4: Commit**

```bash
git add -f docs/phase-theater.html
git commit -m "feat: add Phase III Hosted API demo scene to phase-theater"
```

---

## Task 6: Phase IV Scene — "Adaptive Intelligence"

Build the health monitor demo with visual diff and autonomy spectrum.

**Files:**
- Modify: `docs/phase-theater.html`

**Step 1: Define Phase IV stage HTML**

Split-view with wireframe schematics:

```html
<div class="health-monitor">
  <div class="health-panel">
    <div class="health-panel-header">Expected</div>
    <div class="wireframe" id="wireframe-expected">
      <!-- Simplified boxes representing portal elements -->
      <div class="wireframe-element" data-label="Nav: Home | Reports | Settings"></div>
      <div class="wireframe-element" data-label="Login Button" id="expected-login-btn"></div>
      <div class="wireframe-element" data-label="Employee ID" id="expected-field-label"></div>
      <div class="wireframe-element" data-label="Password"></div>
    </div>
  </div>
  <div class="health-panel">
    <div class="health-panel-header">Actual</div>
    <div class="wireframe" id="wireframe-actual">
      <div class="wireframe-element" data-label="Nav: Home | Reports | API Access | Settings" id="actual-nav"></div>
      <div class="wireframe-element" data-label="Submit" id="actual-login-btn"></div>
      <div class="wireframe-element" data-label="Worker ID" id="actual-field-label"></div>
      <div class="wireframe-element" data-label="Password"></div>
    </div>
  </div>
</div>
<div class="autonomy-bar" id="autonomy-bar">
  <div class="autonomy-segment auto-repair" style="width:40%">Auto-repair</div>
  <div class="autonomy-segment propose" style="width:35%">Propose + Approve</div>
  <div class="autonomy-segment human-only" style="width:25%">Human Only</div>
</div>
<div id="health-counter" style="text-align:center;margin-top:12px;color:var(--muted);font-size:0.85rem;opacity:0;"></div>
```

**Wireframe elements** are styled as simple bordered rectangles with their `data-label` shown as text inside. They use `position: relative` so they can be animated.

**Step 2: Define Phase IV scene**

1. `sleep(600)` — let wireframes render
2. `diffHighlight` on `#actual-login-btn` — orange border appears (label shows "Submit" vs expected "Login Button")
3. `sleep(400)`
4. `diffHighlight` on `#actual-field-label` — orange border (label "Worker ID" vs "Employee ID")
5. `sleep(400)`
6. `diffHighlight` on `#actual-nav` — orange border (new "API Access" nav item)
7. `sleep(600)`
8. `appendLine` to `#phase-response` — "Scheduled health scan complete — 3 changes detected"
9. `appendLine` — "1. Login button: `#btn-login` → `.auth-submit`" + Classification: Cosmetic + Action: Auto-repair applied (green)
10. `appendLine` — "2. Form label: 'Employee ID' → 'Worker ID'" + Classification: Cosmetic + Action: Auto-repair applied (green)
11. `appendLine` — "3. New nav item: 'API Access'" + Classification: Structural + Action: Flagged for human review (yellow)
12. Animate autonomy bar: green widens to 55%, yellow stays at 30%, red narrows to 15% (CSS transition on width)
13. `counterUpdate` on `#health-counter` — "Portal integrations monitored: 247 — Auto-healed this week: 31"
14. `appendLine` — closing line: "1,000 portals ≠ 1,000 engineers."

**Step 3: Register phase and test**

```javascript
PhaseController.phases[3] = {
  stageHtml: phaseIVStageHtml,
  scene: phaseIVScene,
  title: 'Adaptive Intelligence',
  subtitle: 'Claude API — Proactive Change Detection',
  audience: 'Platform-Wide',
  validates: 'Operational scalability without proportional human intervention',
};
```

Test: `PhaseController.jumpToPhase(3)` in console. Wireframes should appear, diff highlights should animate in, Claude analysis should play, autonomy bar should shift, counter should fade in.

**Step 4: Commit**

```bash
git add -f docs/phase-theater.html
git commit -m "feat: add Phase IV Adaptive Intelligence demo scene to phase-theater"
```

---

## Task 7: Architecture Stack Capstone

Add the animated architecture layers that appear after Phase IV.

**Files:**
- Modify: `docs/phase-theater.html`

**Step 1: Build architecture section HTML**

Add to the `#architecture` section (initially hidden with `.hidden` class):

```html
<div class="section hidden" id="architecture">
  <div class="section-divider"></div>
  <h2 class="section-header">How it all connects</h2>
  <p class="section-subtitle">The full stack — from browser runtime to client systems.</p>
  <div class="arch-stack">
    <!-- Layers ordered top-to-bottom (client → browser) -->
    <div class="arch-layer" style="--layer-color: #94A3B8; transform: translateY(30px); opacity: 0;">
      <div class="arch-layer-name">Client Systems</div>
      <div class="arch-layer-items">ERP &middot; HRIS &middot; Payroll Engine &middot; Custom Apps</div>
    </div>
    <!-- ... repeat for all 6 layers ... -->
    <div class="arch-layer" style="--layer-color: #8B5CF6; transform: translateY(30px); opacity: 0;">
      <div class="arch-layer-name">Browser Runtime</div>
      <div class="arch-layer-items">Headless Chromium Pool &middot; Session Management &middot; Anti-Detection &middot; Portal Connectors</div>
    </div>
  </div>
</div>
```

Each `.arch-layer` uses `border-left: 4px solid var(--layer-color)` for its accent color. Layers start with `transform: translateY(30px); opacity: 0` and are animated in by `playArchitecture()`.

**Step 2: Verify architecture animation**

Open the page, run `PhaseController.playArchitecture()` in console. The architecture section should become visible, and layers should slide in from bottom to top with staggered timing.

**Step 3: Commit**

```bash
git add -f docs/phase-theater.html
git commit -m "feat: add architecture stack capstone to phase-theater"
```

---

## Task 8: Auto-Play + Final Wiring + Polish

Wire everything together: auto-play on load, timeline interactions, responsive cleanup.

**Files:**
- Modify: `docs/phase-theater.html`

**Step 1: Wire auto-play on load**

```javascript
// Auto-play after brief delay
setTimeout(() => PhaseController.playAll(), 800);
```

**Step 2: Add phase meta display**

When a phase plays, show its audience label and "validates" text below the stage:
- Audience badge: colored pill (green for "Internal", cyan for "Internal → External", etc.)
- Validates line: italicized muted text

**Step 3: Polish timeline progress animation**

The `.timeline-progress` bar should smoothly animate its width as phases progress. Add CSS `transition: width 0.5s ease` and ensure `updateTimeline()` sets the correct width at each phase boundary.

**Step 4: Add responsive breakpoints**

At `max-width: 768px`:
- API console panels stack vertically
- Health monitor panels stack vertically
- Timeline nodes get smaller text
- Architecture layers get tighter padding

**Step 5: Full end-to-end test**

Open `docs/phase-theater.html` in a browser. Verify:
1. Page loads with header and timeline visible
2. After ~800ms, Phase I auto-plays (browser chrome + tool calls)
3. Phase I completes, timeline updates, Phase II starts after a brief pause
4. Phase II shows dashboard, failure/self-healing narrative plays
5. Phase III shows API console, curl types, JSON response appears
6. Phase IV shows health monitor, diffs highlight, analysis plays
7. Architecture stack animates in
8. Replay button appears
9. Clicking a timeline node jumps to that phase and plays its demo
10. Clicking Replay restarts from Phase I
11. Page looks correct at 768px width

**Step 6: Commit**

```bash
git add -f docs/phase-theater.html
git commit -m "feat: complete phase-theater with auto-play, timeline, and responsive polish"
```

---

## Summary

| Task | Description | Est. Lines |
|------|-------------|-----------|
| 1 | Scaffold: HTML + CSS | ~650 |
| 2 | AnimationEngine + PhaseController | ~250 |
| 3 | Phase I scene | ~120 |
| 4 | Phase II scene | ~130 |
| 5 | Phase III scene | ~110 |
| 6 | Phase IV scene | ~140 |
| 7 | Architecture stack | ~80 |
| 8 | Auto-play + polish | ~50 |
| **Total** | | **~1,530** |

Each task produces a testable, committable increment. The page works (partially) after every commit.
