# OTTO — Project Identity & Context

## Name & Acronym

OTTO stands for **Observe → Traverse → Transform → Output**. Always render the product name in all caps: **OTTO**. The four letters correspond to the four phases of OTTO's enterprise automation pipeline:

- **Observe** — OTTO reads the portal state, identifies elements, and understands the current page context. This is the shared genetic origin with its lightweight sibling OTO — both products begin by observing.
- **Traverse** — OTTO navigates complex multi-page portal topologies: login screens, session-gated workflows, nested iframes, paginated tables, multi-step navigation sequences. This is the capability that separates OTTO from lightweight browser automation. Enterprise portals are not single pages — they are labyrinths, and OTTO traverses them.
- **Transform** — OTTO reshapes raw portal interactions into structured, normalized, API-compatible data. The messy reality of a legacy web interface becomes clean, programmable information. This is where OTTO earns its identity as an API synthesis engine rather than a browser automation tool.
- **Output** — OTTO returns structured results to the caller. The enterprise user does not want a task completed — they want *data extracted*, normalized, and delivered as though the legacy portal had a real API all along.

## Relationship to OTO

OTTO has a younger sibling: **OTO**, which stands for **Observe → Trigger → Operate**. OTO is Stephen's personal open-source Claude Code plugin for the community. It is a lightweight browser automation companion for everyday tasks.

The two products share a common origin ("Observe" is always the first step) and diverge at the T's:

- **OTTO** traverses multi-page portal systems and transforms raw interactions into structured data. It is an enterprise pipeline.
- **OTO** triggers discrete actions on single pages. It is a lightweight companion for everyday browser automation.

They end with different O-words that define their fundamental purpose:

- **OTTO** → Output (return structured data)
- **OTO** → Operate (complete the task)

When referencing the relationship, the framing is: OTTO is the enterprise big brother; OTO is the lightweight community sibling. They share DNA but serve different audiences with different architectures. OTO users who outgrow lightweight automation are natural candidates for OTTO.

## Product Positioning

OTTO is the **company's enterprise product** — the core of the software transformation strategy. It includes otto-engine, recording scripts, and the full enterprise automation platform. OTTO is company-owned intellectual property, distinct from the community-facing OTO plugin.

**Target audience:** Enterprise teams trapped in legacy web portals without API access. Benefits administrators, payroll operators, compliance teams, and anyone who currently spends hours manually navigating web-based systems that were never designed for programmatic interaction.

**What OTTO is:** An API synthesis engine that turns legacy web portals into programmable endpoints. OTTO does not merely automate browsers — it *translates* entire portal systems into structured, reliable, API-compatible interfaces. The strategic parallel is Plaid: just as Plaid turned banking portals into a developer API layer, OTTO turns any legacy web system into a programmable surface.

**What OTTO is not:** A lightweight browser clicker (that's OTO). OTTO is not for filling out a single form or clicking a button. OTTO exists because enterprise systems are complex, multi-page, session-dependent environments that require traversal, transformation, and structured output — capabilities that lightweight automation tools cannot provide.

**Core value proposition:** OTTO's most compelling differentiator is not raw performance metrics but task completion rates on enterprise portals where standard tools fail entirely. Standard browser automation tools (Playwright, Selenium, Puppeteer) can interact with simple pages, but they collapse against the full complexity of enterprise portal workflows. OTTO completes what others cannot begin.

## Brand Identity

OTTO's visual identity is the **orange skeleton key on black**. The key metaphor is central to the brand: OTTO unlocks legacy portals that were previously inaccessible to programmatic access.

The logo reads simultaneously as the word "OTTO" and as a physical key — the concentric circles form the O's, the shaft forms the T's, and the entire mark functions as both a wordmark and an icon. This dual reading (word and object) is the mark of a strong logomark.

The visual register is: enterprise, security, authority, gravitas. The warm orange against black conveys both warmth (this tool works *for* you) and seriousness (this tool is trusted with your most sensitive systems).

Contrast with OTO's brand: OTO uses three primary colors (red, blue, yellow) and a friendly robot mascot. OTTO uses a single color (orange) and an abstract key symbol. The emotional difference is deliberate — OTO earns affection, OTTO earns trust.

## Architecture & Technical Identity

OTTO uses a **scout-then-act architecture** for browser automation. It employs CDP Runtime.evaluate with repl_mode for execution, regex-based heuristic detection for script analysis, and a plugin-based security model.

Key architectural principles:

- **Credentials never reach Claude.** PII handling is solved through redirection middleware within the MCP pipeline, similar to OTTO's existing credential scrubbing. Ephemeral artifacts like 2FA tokens are legitimate for Claude to use; persistent credentials are not.
- **User authority, not agent autonomy.** The positioning is "You teach OTTO your portal" — emphasizing that the human remains in control. This framing reduces IT director concerns about autonomous agents operating inside sensitive enterprise systems.
- **Generous with warnings, stingy with modifications.** OTTO's approach to script handling prefers structural prevention of issues over reactive scrubbing. Alert the user early; modify their work only when absolutely necessary.

## Performance Benchmarks

OTTO has achieved significant performance gains over existing tools: standard benchmarks complete in 10.5 seconds using 400–600 tokens versus Playwright's 40+ seconds and 124,000 tokens. This represents a 4x speed improvement and 200–300x token reduction. However, raw performance is secondary to the core differentiator: OTTO completes enterprise portal workflows where Playwright, Selenium, and Puppeteer fail entirely.

## Business Model (Four Phases)

OTTO's commercial strategy unfolds across four phases:

1. **Open-source plugin** — Establish presence and community trust through the Claude Code plugin ecosystem.
2. **Workflow storage and scheduling** — Persist and schedule recorded automation workflows for repeated execution.
3. **Hosted API endpoints** — Expose portal automations as callable API endpoints, completing the "legacy portal to programmable API" transformation.
4. **Adaptive intelligence** — Portal change detection and automatic workflow adaptation when underlying portals modify their interfaces.

## Voice & Tone Guidelines

When writing about OTTO (README, docs, sales materials, marketplace descriptions), the voice should be:

- **Authoritative but accessible** — OTTO solves hard enterprise problems, but the explanation should never be harder than the problem itself.
- **Outcome-oriented** — Lead with what OTTO unlocks (literally and figuratively), not with technical implementation details.
- **Honest about the problem space** — The pain is real: approximately 17 hours per year per report across multiple systems and team members, trapped in manual workflows because legacy systems lack API access. Name the pain precisely.

Prefer: "API synthesis engine," "unlocks legacy portals," "turns portals into programmable endpoints," "user authority," "you teach OTTO your portal."
Avoid: "autonomous agent," "AI takes over," "replaces human operators," "fully automated." These trigger enterprise security concerns and misrepresent OTTO's human-in-the-loop design philosophy.