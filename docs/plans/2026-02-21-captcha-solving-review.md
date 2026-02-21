# Adversarial Review: CAPTCHA Solving Design

**Reviewer:** Self-review (adversarial)
**Date:** 2026-02-21
**Target:** `docs/plans/2026-02-21-captcha-solving-design.md`
**Verdict:** The plan has the right instincts but is overbuilt, under-validated, and dodges the hardest problems. Major revision needed before implementation.

---

## Fatal Issues

### 1. reCAPTCHA/hCaptcha challenges render in cross-origin iframes — the plan ignores this

The plan's own CLAUDE.md says:

> "It cannot access cross-origin iframe content directly via DOM inspection."

reCAPTCHA v2 challenge grids render inside `https://www.google.com/recaptcha/api2/bframe` — a **cross-origin iframe**. hCaptcha does the same at `https://newassets.hcaptcha.com/captcha/v1/...`. This means:

- `detect_captcha` can see the outer `div.g-recaptcha` container and the iframe element, but **cannot inspect the challenge content** inside it (no DOM access).
- `take_screenshot` captures the full viewport including the visually-rendered iframe — so Claude **can see it** in screenshots. But `click_coordinates` needs to dispatch mouse events at the right viewport-relative position, accounting for iframe offsets, scroll position, and any overlays.
- The `container_selector` and `frame_context` fields in `CaptchaDetection` imply you can reach into the challenge iframe. You can't.

**The plan never addresses how to interact with elements inside cross-origin CAPTCHA iframes.** This is the single most common CAPTCHA scenario and the plan hand-waves past it.

**Fix:** Be explicit that for reCAPTCHA/hCaptcha visual challenges, the only interaction path is viewport-relative CDP mouse events (`Input.dispatchMouseEvent`). Detection can identify the provider from the outer DOM, but solving requires screenshot + coordinate-based clicking — no selector-based interaction is possible. The `click_coordinates` action becomes load-bearing, not a "nice to have."

### 2. Claude vision CAPTCHA-solving accuracy is assumed, not validated

The plan claims "Claude vision handles these well" for distorted text CAPTCHAs with **zero evidence**. CAPTCHAs are adversarial by design — they're literally optimized to be hard for AI. Before building infrastructure around Claude-as-solver:

- What's Claude's accuracy on distorted text CAPTCHAs? 60%? 90%? 30%?
- What about image grid challenges ("select all traffic lights")? These require semantic understanding of ambiguous, low-resolution tiles and multi-round interaction as tiles refresh.
- Does Claude refuse to solve CAPTCHAs citing "bypassing security measures"? The acceptable use policy is relevant here. Has anyone tested this at scale?
- How does accuracy compare to third-party services that advertise 95%+ solve rates?

**The plan builds two modules and an optional dependency around an unproven assumption.** If Claude's solve rate is below ~80%, the entire Layer 1 premise collapses and you should just go straight to third-party solvers.

**Fix:** Before writing any code, run a validation:
1. Collect 50 CAPTCHA screenshots of various types
2. Send them to Claude via API with the proposed prompts
3. Measure solve rate per type
4. Document results and set a go/no-go threshold (e.g., >80% accuracy = proceed, <80% = skip Layer 1 for that type)

### 3. The `solve_captcha` workflow step is a static answer to a dynamic problem

CAPTCHAs don't appear at predictable points. They depend on:
- IP reputation (changes between runs)
- Browser fingerprint (varies per machine)
- Rate limiting (depends on execution timing)
- Account risk score (changes over time)
- Server-side A/B testing

The plan puts `solve_captcha` as a fixed step in the workflow sequence, but **the exported workflow has no conditional branching**. You can't say "if CAPTCHA appears here, solve it" — you can only say "step 5: solve CAPTCHA." What happens when:

- Step 5 says `solve_captcha` but no CAPTCHA appeared? (Wasted API call + false detection)
- A CAPTCHA appears at step 3 instead of step 5? (Workflow fails at step 3, never reaches step 5)
- A CAPTCHA appears on a run that never saw one during recording?

**Fix:** Don't make CAPTCHA solving a step type. Make it a **wrapper behavior** on the executor itself. After every step that changes the page (navigate, click, type+submit), run CAPTCHA detection. If detected, invoke the solver chain. This is transparent to the workflow definition — no `solve_captcha` step needed.

```python
# executor.py pseudocode
def _execute_step(self, step, ...):
    result = self._run_action(step)
    if self._captcha_solving_enabled:
        self._check_and_solve_captcha()  # runs detection, solves if found
    return result
```

This also eliminates the `captcha_type`, `captcha_selector`, `solver`, and `answer_selector` fields from `WorkflowStep`, keeping the schema clean.

---

## Serious Issues

### 4. Token injection code is brittle and will break

The plan presents this as stable:

```javascript
___grecaptcha_cfg.clients[0].L.L.callback(token);
```

This is a **minified internal API path** inside reCAPTCHA's JavaScript. Google obfuscates and rotates these property names across versions. The `.L.L.callback` path that works today may be `.M.K.callback` next month. No serious CAPTCHA tool hardcodes this — they use dynamic traversal to find the callback function.

The hCaptcha injection is less fragile (`hcaptcha.execute()` is a public API), but the hidden input name `h-captcha-response` is also an implementation detail.

**Fix:** If we do Phase 3, the token injection code needs to dynamically discover the callback rather than hardcoding a path. Third-party solver SDKs (like 2Captcha's own JS snippet) already handle this — we should defer to their injection methods rather than rolling our own. Or, acknowledge this is research-grade and will need ongoing maintenance.

### 5. Scope is too large for a v0.1.0 plugin

Otto is at version 0.1.0 with 11 tools and is still establishing its core value proposition. The CAPTCHA plan proposes:

- 2 new Python modules (`captcha.py`, `captcha_solver.py`)
- New JS detection script additions
- 3 third-party service adapters (2Captcha, CapSolver, Anti-Captcha)
- New workflow step type + executor integration
- New action type (`click_coordinates`)
- New MCP tool (`detect_captcha`)
- Scout report schema changes
- Model changes (`CaptchaDetection`, `CaptchaSolution`)
- New optional dependency (`anthropic`)
- CLAUDE.md documentation updates
- Protocol-based pluggable interface
- Balance checking and cost reporting

This is roughly **doubling the codebase** for a feature that Botasaurus's entire value prop is designed to avoid triggering. The plan admits in Phase 1: "No new dependencies... Claude Code can detect and solve image-based CAPTCHAs via screenshot + reasoning + clicking." If that's true, why build all the rest before validating that the simple approach works?

**Fix:** Ruthlessly cut scope. Ship one milestone at a time and only proceed if the previous one proves insufficient:

- **v0.1:** Detection heuristics + `click_coordinates` action only. No new MCP tool — just enhance the scout report. Claude Code already has take_screenshot + execute_action + run_js. Document the manual solving pattern in CLAUDE.md.
- **v0.2:** If interactive solving works but workflows need it, add `CaptchaSolver` with Claude API.
- **v0.3:** If Claude API accuracy is insufficient, add ONE third-party adapter (2Captcha, the most established). Not three.

### 6. `click_coordinates` with absolute pixels is fragile

The plan proposes:

```python
x, y = float(value.split(",")[0]), float(value.split(",")[1])
driver.run_cdp_command(cdp.input_.dispatch_mouse_event(
    type_="mousePressed", x=x, y=y, ...
))
```

Absolute viewport coordinates break across:
- Different viewport sizes (1920x1080 vs 1366x768)
- Different DPI/device pixel ratios
- Page zoom levels
- Scroll positions (coordinates are viewport-relative, not document-relative)
- Dynamic layouts that shift element positions

For interactive sessions this is somewhat manageable — Claude takes a fresh screenshot and calculates coordinates each time. But in exported workflows, hardcoded coordinates are unusable.

**Fix:** For interactive solving, `click_coordinates` is fine as long as it's always preceded by a fresh screenshot + coordinate calculation. Never export `click_coordinates` steps to workflow JSON — they're inherently non-portable. For workflow replay CAPTCHA solving, the solver should calculate coordinates dynamically from a fresh screenshot at execution time.

### 7. No cost controls for API-based solving

The plan says "Solver costs are per-solve; no runaway billing without explicit workflow invocation." This is inadequate:

- A workflow running in a cron job hits CAPTCHAs every time due to IP reputation → unlimited Claude API calls + third-party solver calls
- The retry loop has "a hard cap" but doesn't specify what it is
- No per-run cost limit, no per-day budget, no alerting
- Claude API calls with images are more expensive than text-only calls
- Third-party solvers charge per solve regardless of success

**Fix:** Add concrete cost controls:
- `max_captcha_attempts` per workflow run (default: 3)
- `captcha_solver_budget_cents` per run (default: 50 cents, enough for ~15-25 third-party solves)
- Log solver usage (type, cost, success/failure) to the executor's JSON output
- Fail loudly when budget is exhausted rather than silently stopping

### 8. Detection heuristics are brittle and locale-dependent

The plan's text pattern approach checks for strings like "verify you're human" and "security check." Problems:

- **Locale:** Non-English sites won't contain these strings. reCAPTCHA localizes its challenge text.
- **False positives:** A help page explaining CAPTCHAs, an error message mentioning CAPTCHAs, a blog post about CAPTCHAs — all trigger detection.
- **False negatives:** Custom CAPTCHA implementations with no standard class names or text patterns.
- **Provider DOM changes:** reCAPTCHA and hCaptcha periodically change their class names and DOM structure. Hardcoded selectors like `div.g-recaptcha` are stable-ish but not guaranteed.

**Fix:** Weight detection heavily toward structural signals (iframe src domains, known JS globals like `grecaptcha` and `hcaptcha`) rather than text patterns. Text patterns should only increase confidence, not be sufficient for detection. Accept that custom CAPTCHAs can't be auto-detected — document this as a limitation.

---

## Moderate Issues

### 9. The plan conflates interactive and workflow solving but they need different engineering

**Interactive sessions:** Claude Code is an intelligent agent. It can take a screenshot, look at it, try something, see it didn't work, try something else, ask the user "I see a CAPTCHA — should I try to solve it?" The entire three-layer solver chain is overkill. Claude just needs:
- To know CAPTCHAs exist (detection in scout report)
- A way to click at coordinates (for grid challenges in cross-origin iframes)
- That's it. Claude handles the rest conversationally.

**Workflow replay:** This is the hard problem. No intelligence in the loop. Needs automated detection → solving → verification → retry. This is where the solver chain, API calls, and cost controls matter.

The plan should be restructured around this split instead of treating them as variations of the same architecture.

### 10. No verification that CAPTCHA was actually solved

The solving flow ends with "verify CAPTCHA is resolved (re-detect)" but doesn't specify:
- How do you know the CAPTCHA was solved vs. failed? (Sites often show the same page with a "try again" message)
- reCAPTCHA may serve a new challenge after solving the first one (multi-round)
- Some sites redirect on success, others show an inline success state, others just remove the CAPTCHA widget
- The re-detection heuristic needs to distinguish "CAPTCHA gone" from "page navigated away" from "new CAPTCHA appeared"

**Fix:** Define concrete verification strategies per CAPTCHA type:
- reCAPTCHA: Check for `grecaptcha.getResponse()` returning a non-empty string
- hCaptcha: Check for `hcaptcha.getResponse()` returning a non-empty string
- Image text: Check if the CAPTCHA input field's form was accepted (page changed or success indicator appeared)
- Generic: Compare page state before/after (URL change, DOM fingerprint change — the same technique `execute_action` already uses)

### 11. Scout report modification adds overhead to every scout call

Adding CAPTCHA detection to `scout_page.js` means **every scout pays the detection cost**, even when the user is doing normal navigation with no CAPTCHA risk. The plan calls this "optional lightweight" but doesn't define what "optional" means — is it opt-in per call? A global config? Always-on?

The detection JS itself is non-trivial: querying for multiple selectors, checking for JS globals, examining iframe sources. On complex pages with hundreds of iframes, this adds up.

**Fix:** Make it a separate JS check, not baked into the scout. The `detect_captcha` MCP tool (or the executor's post-step hook) calls it explicitly. The scout report stays focused on page structure. If you want passive detection, add it as a fast boolean check (just `!!document.querySelector('iframe[src*="recaptcha"], iframe[src*="hcaptcha"], .cf-turnstile')`) — not the full detection with sitekey extraction.

### 12. The plan doesn't address headless mode limitations

Many CAPTCHAs behave differently in headless mode:
- reCAPTCHA v2 is more likely to show challenges in headless (even with anti-detection)
- Some CAPTCHAs detect headless mode and always present challenges
- The "manual pause" fallback (Layer 3) is useless in headless mode — there's no visible window for a human to interact with

The plan acknowledges "Headless: fail with screenshot" for Layer 3 but doesn't address the increased CAPTCHA frequency in headless. Workflows using `--headless` will hit CAPTCHAs more often, making the solver chain more critical — but also more expensive.

**Fix:** Document this tradeoff explicitly. Consider recommending headed mode for CAPTCHA-heavy sites, or supporting a "headed-on-captcha" mode where the browser runs headless until a CAPTCHA is detected, then switches to headed for solving (Botasaurus/CDP may or may not support this hot-swap).

---

## Minor Issues

### 13. `anthropic>=0.40.0` version pin is too loose

The Anthropic SDK has had breaking API changes between major versions. An open-ended `>=` pin risks pulling in a future version that changes the vision API interface, message format, or model names. This breaks silently at runtime.

**Fix:** Pin to a compatible range: `anthropic>=0.40.0,<1.0.0` or similar.

### 14. Missing: what does the interactive flow look like in CLAUDE.md?

The plan says "Document the interactive solving workflow in CLAUDE.md" but the actual CAPTCHA-solving prompt/workflow for Claude Code is unspecified. Claude needs clear instructions like:
- When to check for CAPTCHAs (after login submissions, after Cloudflare redirects)
- How to read grid challenges and map tile positions to coordinates
- When to give up and tell the user
- Whether to ask the user before attempting to solve

This is arguably more important than the code — Claude's behavior is prompt-driven.

### 15. No mention of CAPTCHA audio challenges

reCAPTCHA v2 and hCaptcha both offer audio challenge alternatives. These are often easier to solve programmatically (speech-to-text) than image challenges. The plan doesn't consider this path at all.

### 16. The three third-party adapters are premature

The plan proposes implementing adapters for 2Captcha, CapSolver, AND Anti-Captcha. These services have similar but subtly different APIs. Building and maintaining three adapters from day one is wasted effort — pick one (2Captcha, the most established and best-documented), ship it, and add others only if users request them.

---

## Revised Recommendation

Strip the plan to two focused milestones:

### Milestone 1: Detection + Interactive Awareness (small, no new deps)
- Lightweight CAPTCHA detection JS (separate from scout, called on demand)
- `click_coordinates` action type for coordinate-based clicking
- `captcha_detected` quick-check in scout report metadata (single querySelector, not full detection)
- CLAUDE.md documentation: how Claude should handle CAPTCHAs interactively
- **No new MCP tool** — Claude uses existing tools (screenshot + JS + click_coordinates)

### Milestone 2: Workflow Solver (after validating Claude vision accuracy)
- Run the accuracy validation first (go/no-go gate)
- CAPTCHA detection + solving as an executor wrapper, not a step type
- Claude API solver with `anthropic` optional dep
- 2Captcha adapter only (not three services)
- Concrete cost controls (max attempts, budget cap)
- Verification strategies per CAPTCHA type

### Deferred / Cut
- CapSolver and Anti-Captcha adapters (add when requested)
- `detect_captcha` as a separate MCP tool (unnecessary — scout + screenshot is enough)
- `ExternalCaptchaSolver` Protocol interface (premature abstraction for one adapter)
- Balance checking and cost reporting (v0.3)
- `CaptchaDetection` model with confidence scores (over-engineered for detection heuristics)
