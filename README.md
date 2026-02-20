# Browser Scout

Automate any website by describing what you want in plain English. No web development knowledge required.

Browser Scout is a [Claude Code](https://docs.anthropic.com/en/docs/claude-code) plugin that gives Claude a real browser it can see and control. You describe the task — "log into Paycom, navigate to Census, export the CSV" — and Claude figures out the website for you: the nested iframes, the shadow DOM, the XHR calls, the authentication flow. Then it writes a production-grade automation script you can run on a schedule without Claude.

## Why This Exists

Writing browser automation for enterprise portals is painful. The login form is inside a triple-nested iframe. The export button triggers an XHR that returns a signed URL. The page detects Playwright and blocks you.

Browser Scout solves all three problems:

1. **You don't need to understand the website.** Claude scouts the page structure, discovers what's actually there, and uses exact selectors from reconnaissance — not guesses.
2. **You don't need to write code.** Describe the workflow conversationally. Claude drives the browser step by step, then exports a standalone script.
3. **Sites can't detect the automation.** Built on [Botasaurus](https://github.com/omkarcloud/botasaurus), which handles fingerprint evasion, human-like timing, and stealth browsing automatically — the exact problem Playwright and Puppeteer can't solve.

**New here?** See the [Getting Started guide](docs/getting-started.md) for a full walkthrough with examples.

## Install

```
/plugin marketplace add stemado/browser-scout-marketplace
/plugin install browser-scout@browser-scout-marketplace
```

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (used by the MCP server to manage dependencies)
- Google Chrome or Chromium (Botasaurus drives it via CDP)

Dependencies (`botasaurus-driver`, `mcp`, `pydantic`, `python-dotenv`) are installed automatically by `uv` on first run.

## Usage

Just describe what you want automated:

> "Scout the Paycom login page, log in with the credentials in .env, navigate to Census > Export, and download the CSV"

Claude launches a stealth browser, scouts the page, drives through the workflow step by step, and exports a standalone script when done. You watch it work and redirect as needed — the same way you'd pair-program with a colleague who happens to have a browser open.

### Commands

**`/scout <url>`** — Launch a stealth browser and get a structural overview of any page: iframe hierarchy, shadow DOM boundaries, interactive element counts. The session stays alive for follow-up interactions.

```
/scout https://online.adp.com/signin/v1/
```

**`/export-workflow [name]`** — After completing a workflow interactively, export it as a replayable script. Produces two files in `workflows/`:

- A standalone Python script with numbered, commented steps
- A portable JSON workflow definition (replayable with `workflow-run`)

Credentials are automatically parameterized — real values never appear in the output.

```
/export-workflow adp-report-download
```

**`workflow-run`** — Replay an exported workflow without Claude in the loop. Run it on a schedule, in CI, or as a cron job.

```
workflow-run workflows/adp-report-download.json \
  --var USERNAME=admin --var PASSWORD=s3cret
```

Variables are resolved from CLI args, environment variables, or workflow defaults (in that order). Credential values are masked in output.

```
workflow-run workflows/my-workflow.json --dry-run    # validate and print plan
workflow-run workflows/my-workflow.json --headless   # run headless
```

Each step emits a JSON log line to stdout. Exit code 0 on success, 1 on step failure, 2 on validation error.

## MCP Tools

The plugin exposes 11 tools via MCP:

| Tool | Description |
|------|-------------|
| `launch_session` | Launch a stealth browser with optional URL, proxy, and headless mode |
| `scout_page_tool` | Structural page overview: metadata, iframes, shadow DOM, element counts |
| `find_elements` | Search for interactive elements by text, type, or CSS selector |
| `execute_action_tool` | Perform a single action: click, type, select, navigate, scroll, hover, etc. |
| `fill_secret` | Type a credential from `.env` into a form field without exposing it |
| `execute_javascript` | Run arbitrary JS in the page context |
| `take_screenshot` | Capture a screenshot (returned inline for Claude to inspect visually) |
| `inspect_element` | Deep-inspect a DOM element: visibility, overlays, shadow DOM, ARIA |
| `monitor_network` | Capture network traffic, filter by URL pattern, wait for downloads |
| `get_session_history` | Retrieve the full structured history of the session |
| `close_session` | Close the browser and release resources |

## How It Compares

There are several ways to give Claude browser access. They solve different problems.

| | Browser Scout | [Dev-Browser](https://github.com/SawyerHood/dev-browser) | [Claude in Chrome](https://code.claude.com/docs/en/chrome) | [Playwright MCP](https://browsermcp.io/) |
| --- | --- | --- | --- | --- |
| **Primary use case** | Automate sites you've never seen before | Test your own app during development | Debug and inspect pages interactively | Cross-browser test automation |
| **Anti-detection** | Yes (Botasaurus stealth) | No (Playwright) | No (your real browser) | No (Playwright) |
| **Discovers page structure** | Yes (scout + find_elements) | No (you provide selectors) | No (you direct it) | No (you provide selectors) |
| **Exports standalone scripts** | Yes (Python + JSON) | No | No | No |
| **Runs without Claude** | Yes (`workflow-run` CLI) | No | No | No |
| **Credential security** | `.env` injection, never in conversation | N/A | Uses your browser's sessions | N/A |
| **Handles iframes + shadow DOM** | Auto-discovered and navigated | Manual | Manual | Manual |

**When to use Browser Scout:** You need to automate an enterprise portal, HR system, or third-party site where you don't control the HTML, the page uses anti-bot detection, and you want a script that runs unattended.

**When to use something else:** If you're testing your own app (Dev-Browser), debugging a page you're already looking at (Claude in Chrome), or running cross-browser test suites (Playwright MCP).

## License

MIT
