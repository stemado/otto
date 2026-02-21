# CAPTCHA Solving Design

**Date:** 2026-02-21
**Status:** Draft
**Problem:** Botasaurus reduces CAPTCHA frequency via anti-detection, but when CAPTCHAs do appear, Otto can't solve them. Interactive sessions require manual intervention; exported workflows fail entirely.

## Context

Otto operates in two modes that need different CAPTCHA strategies:

1. **Interactive MCP sessions** — Claude Code drives the browser through tool calls. Claude is multimodal and can already see screenshots via `take_screenshot`. The gap is detection and a structured solving flow.
2. **Exported workflow replay** — `workflow-run` executes without Claude in the loop. CAPTCHAs are a hard stop unless the executor can call an external solver.

### CAPTCHA Types Encountered in Practice

| Type | Visual Challenge | Solvable by Vision AI? | Notes |
|------|-----------------|----------------------|-------|
| Distorted text | Read warped characters | Yes — Claude vision handles these well | Classic CAPTCHA, declining in use |
| Image grid ("select all traffic lights") | Click matching tiles | Partially — requires multi-turn clicking | reCAPTCHA v2 / hCaptcha challenge mode |
| reCAPTCHA v2 checkbox | Click "I'm not a robot" | N/A — risk-score based, not visual | Botasaurus usually passes this; challenge only appears on high-risk scores |
| reCAPTCHA v3 | Invisible (score-based) | N/A — no visual element | Botasaurus anti-detection keeps scores high |
| Cloudflare Turnstile | Checkbox or invisible | N/A — proof-of-work based | Botasaurus handles most cases |
| Math / logic CAPTCHAs | "What is 3 + 7?" | Yes | Simple for any LLM |
| Custom site CAPTCHAs | Varies | Depends on challenge type | Site-specific, often simpler |

## Design — Three-Layer Architecture

The CAPTCHA system is a pluggable solver chain. Each layer handles a different set of CAPTCHA types and operates at a different cost/complexity level. The system tries the cheapest approach first and escalates.

```
┌─────────────────────────────────────────────────────┐
│                   CAPTCHA Detected                  │
│              (scout heuristics + JS)                │
└──────────────────────┬──────────────────────────────┘
                       │
           ┌───────────▼────────────┐
           │  Layer 1: Claude Vision │ ← Interactive: free (Claude Code sees it)
           │  (screenshot → reason)  │ ← Workflow: Anthropic API call
           └───────────┬────────────┘
                       │ unsolved?
           ┌───────────▼────────────┐
           │  Layer 2: Third-Party   │ ← 2Captcha / CapSolver / Anti-Captcha
           │  Solver API             │ ← Handles reCAPTCHA tokens, hCaptcha
           └───────────┬────────────┘
                       │ unsolved?
           ┌───────────▼────────────┐
           │  Layer 3: Manual Pause  │ ← Headed mode: wait for human
           │  (existing behavior)    │ ← Headless: fail with screenshot
           └────────────────────────┘
```

---

## Phase 1: CAPTCHA Detection

### New module: `src/otto/captcha.py`

A `CaptchaDetector` class that identifies CAPTCHA presence and type from page state.

**Detection methods (combined for reliability):**

1. **DOM heuristics via JS injection** — Check for known CAPTCHA provider signatures:
   - reCAPTCHA: `iframe[src*="recaptcha"]`, `div.g-recaptcha`, `grecaptcha` globals
   - hCaptcha: `iframe[src*="hcaptcha"]`, `div.h-captcha`
   - Cloudflare Turnstile: `iframe[src*="challenges.cloudflare.com"]`, `div.cf-turnstile`
   - Generic: `img[src*="captcha"]`, `input[name*="captcha"]`, `canvas` elements near submit buttons
   - Text patterns: elements containing "CAPTCHA", "verify you're human", "security check"

2. **URL-based signals** — Page redirected to a challenge page (Cloudflare `/cdn-cgi/challenge-platform/`, generic `/captcha` paths).

3. **Network signals** — Requests to known CAPTCHA provider domains (`google.com/recaptcha`, `hcaptcha.com`, `challenges.cloudflare.com`).

**Output: `CaptchaDetection` model**

```python
class CaptchaDetection(BaseModel):
    detected: bool
    captcha_type: str | None     # "recaptcha_v2", "hcaptcha", "cloudflare", "image_text", "image_grid", "custom", None
    provider: str | None         # "google", "hcaptcha", "cloudflare", None
    container_selector: str | None  # CSS selector of the CAPTCHA container
    frame_context: str | None    # iframe path if CAPTCHA is in an iframe
    challenge_visible: bool      # Whether the challenge UI is currently shown
    sitekey: str | None          # Extracted sitekey for API-based solving
    page_url: str                # Current page URL (needed by solver APIs)
    confidence: float            # 0.0–1.0
```

### New MCP tool: `detect_captcha`

Exposed as a tool so Claude Code can explicitly check for CAPTCHAs after actions that might trigger them (login submissions, form posts).

```python
@mcp.tool()
async def detect_captcha(
    session_id: str,
    ctx: Context = None,
) -> dict:
    """Check if a CAPTCHA challenge is present on the current page."""
```

### Scout integration

Add CAPTCHA detection to `scout_page.js` as an optional lightweight check. The scout report gains a `captcha_detected: bool` field in `page_metadata`. This lets Claude proactively notice CAPTCHAs without an explicit detection call.

---

## Phase 2: Claude Vision Solver

### Interactive sessions (Claude Code)

In an interactive MCP session, Claude Code IS the vision model. The solving flow:

1. `detect_captcha` → identifies type and container
2. `take_screenshot` (clipped to CAPTCHA region using `clip_x/y/width/height` from container bounding rect)
3. Claude sees the screenshot and reasons about the answer
4. `execute_action` to type the answer / click the correct tiles
5. `scout_page` to verify CAPTCHA is resolved

This requires **no new server code** — just a documented workflow pattern. The `detect_captcha` tool provides the container coordinates for targeted screenshots.

For **image grid challenges** (reCAPTCHA "select all X"):
- Screenshot the grid
- Claude identifies which tiles match
- Execute clicks on each matching tile via coordinates
- May require multiple rounds (reCAPTCHA refreshes tiles)
- New helper: `click_coordinates` action (CDP `Input.dispatchMouseEvent` at absolute x,y) to click grid cells without needing individual selectors

### Exported workflows — `CaptchaSolver` class

For `workflow-run` replay without Claude in the loop:

**New module: `src/otto/captcha_solver.py`**

```python
class CaptchaSolver:
    """Solves CAPTCHAs using the Claude API vision capabilities."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def solve_image_captcha(
        self,
        screenshot_bytes: bytes,
        captcha_type: str,
        instructions: str = "",
    ) -> CaptchaSolution:
        """Send a screenshot to Claude and get the CAPTCHA answer."""
        # Build a prompt based on captcha_type:
        # - "image_text": "What text is shown in this CAPTCHA image? Return only the text."
        # - "image_grid": "Which grid squares contain [X]? Return positions as row,col pairs."
        # - "math": "What is the answer to this math problem? Return only the number."
        ...

    def solve_recaptcha_token(
        self,
        sitekey: str,
        page_url: str,
        solver_service: str | None = None,
    ) -> str | None:
        """Delegate reCAPTCHA token generation to a third-party service."""
        # Claude can't solve token-based challenges — delegate to Layer 2
        ...
```

**`CaptchaSolution` model:**

```python
class CaptchaSolution(BaseModel):
    solved: bool
    answer: str | None           # Text answer for input-based CAPTCHAs
    click_positions: list[dict] | None  # [{x, y}, ...] for grid CAPTCHAs
    token: str | None            # reCAPTCHA/hCaptcha token from third-party solver
    confidence: float
    solver_used: str             # "claude_vision", "2captcha", "capsolver", "manual"
    elapsed_ms: int
```

### New dependency

```toml
# pyproject.toml — optional dependency group
[project.optional-dependencies]
captcha = [
    "anthropic>=0.40.0",
]
```

The `anthropic` SDK is an **optional dependency** — only needed for workflow replay CAPTCHA solving. Interactive sessions use Claude Code's built-in vision (no SDK needed). Third-party solvers use HTTP requests (no extra deps).

### New workflow step type: `solve_captcha`

```python
# Added to WorkflowStep.action Literal:
"solve_captcha"

# New fields on WorkflowStep:
captcha_type: str | None          # Expected CAPTCHA type
captcha_selector: str | None      # Container element selector
solver: str | None                # "claude" (default), "2captcha", "capsolver"
answer_selector: str | None       # Where to type the answer (if input-based)
```

**Executor integration (`executor.py`):**

```python
case "solve_captcha":
    # 1. Take screenshot of CAPTCHA region
    # 2. Call CaptchaSolver.solve_image_captcha()
    # 3. If answer: type into answer_selector, submit
    # 4. If click_positions: click each position
    # 5. If token: inject via JS (document.getElementById('g-recaptcha-response').value = token)
    # 6. Verify CAPTCHA is resolved (re-detect)
```

### Environment variables

```env
# .env
ANTHROPIC_API_KEY=sk-ant-...          # Required for Claude vision solver in workflows
CAPTCHA_SOLVER_API_KEY=...            # Optional: 2Captcha/CapSolver API key
CAPTCHA_SOLVER_SERVICE=2captcha       # Optional: which third-party service to use
```

---

## Phase 3: Third-Party Solver Integration

For reCAPTCHA v2/v3 token challenges and hCaptcha, vision-based solving isn't sufficient — these require generating a valid response token by actually completing the challenge through the provider's system. Third-party CAPTCHA solving services handle this.

### Pluggable solver interface

```python
class ExternalCaptchaSolver(Protocol):
    """Interface for third-party CAPTCHA solving services."""

    def solve_recaptcha_v2(self, sitekey: str, page_url: str, timeout_s: int = 120) -> str | None:
        """Returns a g-recaptcha-response token."""
        ...

    def solve_hcaptcha(self, sitekey: str, page_url: str, timeout_s: int = 120) -> str | None:
        """Returns an h-captcha-response token."""
        ...

    def get_balance(self) -> float:
        """Returns remaining account balance."""
        ...
```

### Supported services (initial)

| Service | API | Pricing | Notes |
|---------|-----|---------|-------|
| [2Captcha](https://2captcha.com) | REST | ~$3/1000 solves | Most popular, broad CAPTCHA type support |
| [CapSolver](https://capsolver.com) | REST | ~$2/1000 solves | Newer, good reCAPTCHA/hCaptcha support |
| [Anti-Captcha](https://anti-captcha.com) | REST | ~$2/1000 solves | Long-running, reliable |

### Token injection flow (reCAPTCHA / hCaptcha)

After receiving a token from the third-party service:

```javascript
// reCAPTCHA v2
document.getElementById('g-recaptcha-response').value = token;
// Then trigger the callback:
___grecaptcha_cfg.clients[0].L.L.callback(token);

// hCaptcha
document.querySelector('[name="h-captcha-response"]').value = token;
hcaptcha.execute();
```

This JavaScript injection happens via `execute_javascript` in interactive mode or `driver.run_js()` in workflow replay.

---

## Phase 4: Interactive Solving Enhancements

### `click_coordinates` action

For image grid CAPTCHAs where individual tiles don't have selectors:

```python
# New action in execute_action_tool and WorkflowStep:
case "click_coordinates":
    from botasaurus_driver import cdp
    x, y = float(value.split(",")[0]), float(value.split(",")[1])
    driver.run_cdp_command(cdp.input_.dispatch_mouse_event(
        type_="mousePressed", x=x, y=y, button="left", click_count=1,
    ))
    driver.run_cdp_command(cdp.input_.dispatch_mouse_event(
        type_="mouseReleased", x=x, y=y, button="left", click_count=1,
    ))
```

### CAPTCHA retry loop

In workflow replay, wrap CAPTCHA-sensitive steps:

```python
# Executor pseudo-code for steps following a login/submit:
for attempt in range(max_captcha_retries):
    execute_step(step)
    detection = detect_captcha(driver)
    if not detection.detected:
        break
    solution = solver.solve(detection, driver)
    if solution.solved:
        apply_solution(driver, solution, detection)
    else:
        # Escalate to next solver layer or fail
```

---

## Implementation Order

### Milestone 1 — Detection + Interactive Solving
**Files changed:** `captcha.py` (new), `scout.py`, `models.py`, `server.py`, `js/scout_page.js`

1. `CaptchaDetector` with DOM/URL/network heuristics
2. `CaptchaDetection` model
3. `detect_captcha` MCP tool
4. `captcha_detected` flag in scout report metadata
5. `click_coordinates` action type
6. Document the interactive solving workflow in CLAUDE.md

After this milestone, interactive sessions gain CAPTCHA awareness. Claude Code can detect and solve image-based CAPTCHAs via screenshot + reasoning + clicking. No new dependencies.

### Milestone 2 — Claude Vision Solver for Workflows
**Files changed:** `captcha_solver.py` (new), `workflow.py`, `executor.py`, `models.py`, `pyproject.toml`

1. `CaptchaSolver` class using `anthropic` SDK
2. `CaptchaSolution` model
3. `solve_captcha` workflow step type
4. Executor integration
5. `anthropic` as optional dependency
6. Tests with mock API responses

After this milestone, exported workflows can solve image/text CAPTCHAs autonomously via Claude API. Requires `ANTHROPIC_API_KEY`.

### Milestone 3 — Third-Party Solver Integration
**Files changed:** `captcha_solver.py`, `executor.py`

1. `ExternalCaptchaSolver` protocol
2. 2Captcha adapter
3. CapSolver adapter
4. Token injection helpers (reCAPTCHA, hCaptcha)
5. Solver chain: Claude vision → third-party → manual pause
6. Balance checking / cost reporting

After this milestone, the system can handle reCAPTCHA/hCaptcha token challenges that vision alone can't solve.

---

## What This Won't Solve

- **reCAPTCHA v3 invisible scoring** — No visual challenge to solve. Botasaurus anti-detection is the only defense. If the score is too low, the site may silently block. No solver can help here.
- **Cloudflare Turnstile proof-of-work** — Not a visual challenge. Botasaurus handles most cases natively. If it fails, no solver API helps.
- **100% CAPTCHA elimination** — CAPTCHAs are an arms race. This design handles the common cases but novel challenge types will require updates.
- **Infinite retries on rate-limited challenges** — Some CAPTCHAs lock out after N failures. The retry loop has a hard cap.

## Security Considerations

- `ANTHROPIC_API_KEY` handled like all credentials: loaded from `.env` server-side, never in conversation
- Third-party solver API keys same treatment
- Screenshot bytes sent to Claude API are transient (not stored by Anthropic per API data policy)
- CAPTCHA tokens are short-lived and site-specific — no persistence risk
- Solver costs are per-solve; no runaway billing without explicit workflow invocation
