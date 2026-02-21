<p align="center">
  <img src="assets/logo.png" alt="Otto" width="400">
</p>

<p align="center">
  <em>Automate any website by describing what you want in plain English.<br>
  No web development knowledge required.</em>
</p>

---

Most browser plugins let Claude interact with pages you already understand. Otto is built for the opposite scenario: enterprise portals, vendor dashboards, and third-party sites where you don't control the HTML, the page actively resists automation, and you need a script that runs unattended — without Claude in the loop.

Otto is a [Claude Code](https://docs.anthropic.com/en/docs/claude-code) plugin. You describe a task conversationally — *"log into ADP, navigate to Census, export the CSV"* — and Claude scouts the page structure, drives a stealth browser through the workflow, and exports a standalone Python script you can run on a schedule. Built on [Botasaurus](https://github.com/omkarcloud/botasaurus) for fingerprint evasion, so the sites that block Playwright and Puppeteer don't block Otto.

## The Problem

Enterprise portals are hostile terrain for automation. The login form lives inside a triple-nested iframe. The export button triggers an XHR that returns a signed URL. The page fingerprints your browser and blocks anything that smells like Playwright.

Otto handles all of this so you don't have to. Claude scouts the page, discovers selectors from reconnaissance rather than guesswork, drives the workflow step by step, and exports a production-grade script — no web development knowledge required.

> **New here?** The [Getting Started guide](docs/getting-started.md) walks through a complete example from scout to scheduled script.

## Install

```
/plugin marketplace add stemado/otto-marketplace
/plugin install otto@otto-marketplace
```

### Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) — used by the MCP server to manage dependencies
- Google Chrome or Chromium — Botasaurus drives it via CDP

Dependencies (`botasaurus-driver`, `mcp`, `pydantic`, `python-dotenv`) are installed automatically by `uv` on first run.

## Usage

Describe what you want automated:

> "Scout the ADP login page, log in with the credentials in .env, navigate to Census > Export, and download the CSV."

Claude launches a stealth browser, scouts the page, drives through the workflow, and exports a standalone script when done. You watch it work and redirect as needed — the same way you'd pair-program with a colleague who happens to have a browser open.

### `/scout <url>`

Launch a stealth browser and get a structural overview of any page: iframe hierarchy, shadow DOM boundaries, interactive element counts. The session stays alive for follow-up interactions.

```
/scout https://online.adp.com/signin/v1/
```

### `/export-workflow [name]`

After completing a workflow interactively, export it as a replayable script. Produces two files in `workflows/`:

- A standalone Python script with numbered, commented steps
- A portable JSON workflow definition (replayable via `workflow-run`)

Credentials are automatically parameterized — real values never appear in the output.

```
/export-workflow adp-report-download
```

### `workflow-run`

Replay an exported workflow without Claude in the loop. Intended for schedules, CI pipelines, and cron jobs.

```
workflow-run workflows/adp-report-download.json \
  --var USERNAME=admin --var PASSWORD=s3cret
```

Variables resolve from CLI args first, then environment variables, then workflow defaults. Credential values are masked in all output.

```
workflow-run workflows/my-workflow.json --dry-run    # validate and print plan
workflow-run workflows/my-workflow.json --headless   # run without a visible browser
```

Each step emits a JSON log line to stdout. Exit codes: `0` success, `1` step failure, `2` validation error.

## MCP Tools

Otto exposes 11 tools via MCP, organized by function:

**Session lifecycle** — `launch_session` · `close_session` · `get_session_history`

**Reconnaissance** — `scout_page_tool` · `find_elements` · `inspect_element` · `take_screenshot`

**Interaction** — `execute_action_tool` · `fill_secret` · `execute_javascript`

**Observation** — `monitor_network`

| Tool | Purpose |
|------|---------|
| `launch_session` | Open a stealth browser with optional URL, proxy, and headless mode |
| `scout_page_tool` | Structural page overview: metadata, iframes, shadow DOM, element counts |
| `find_elements` | Search for interactive elements by text, type, or CSS selector |
| `execute_action_tool` | Perform a single action: click, type, select, navigate, scroll, hover |
| `fill_secret` | Type a credential from `.env` into a form field without exposing it |
| `execute_javascript` | Run arbitrary JS in the page context |
| `take_screenshot` | Capture a screenshot for Claude to inspect visually |
| `inspect_element` | Deep-inspect a DOM element: visibility, overlays, shadow DOM, ARIA |
| `monitor_network` | Capture network traffic, filter by URL pattern, wait for downloads |
| `get_session_history` | Retrieve the full structured action history of the session |
| `close_session` | Close the browser and release resources |

## When to Use What

Several tools give Claude browser access. They solve different problems.

**Otto** is for automating sites you don't control — enterprise portals, HR systems, vendor dashboards — where the HTML is hostile, anti-bot detection is present, and you want a script that runs unattended. Otto discovers page structure for you, handles stealth, and exports standalone workflows.

**[Dev-Browser](https://github.com/SawyerHood/dev-browser)** is for testing your own application during development. You provide the selectors; it drives Playwright against known HTML.

**[Claude in Chrome](https://code.claude.com/docs/en/chrome)** is for interactive debugging and inspection. It operates inside your real browser session — useful when you're already looking at the page and want Claude to help you understand or manipulate it.

**[Playwright MCP](https://browsermcp.io/)** is for cross-browser test automation. You provide selectors and assertions; it runs deterministic test suites across engines.

The distinguishing characteristics of Otto are anti-detection stealth (via Botasaurus), automatic page structure discovery, and the ability to export workflows that run independently of Claude.

## License

MIT
