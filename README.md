# Browser Scout

Stealth browser reconnaissance plugin for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Scout websites interactively, then compose production-grade automation scripts with anti-detection built in.

Built on [Botasaurus](https://github.com/omkarcloud/botasaurus), which handles fingerprint evasion, human-like timing, and stealth browsing automatically — the exact problem Playwright and Puppeteer can't solve.

## What It Does

Browser Scout gives Claude a live browser it can drive interactively. Instead of guessing at page structure, Claude scouts the DOM incrementally — discovering nested iframes, shadow DOM boundaries, and network behavior — then uses exact selectors from reconnaissance to compose scripts.

**The workflow:**

1. **Scout** — Launch a stealth browser and inspect page structure
2. **Interact** — Click, type, navigate, fill forms step by step
3. **Observe** — Re-scout after each action to see what changed
4. **Export** — Generate a standalone botasaurus-driver Python script from the session

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

### `/scout <url>`

Launch a stealth browser, scout the page, and get a structural overview:

```
/scout https://example.com/login
```

Returns: page title, iframe hierarchy, shadow DOM boundaries, and interactive element counts. The session stays alive for follow-up interactions.

### `/export-workflow [name]`

After completing a workflow interactively, export it as a replayable script:

```
/export-workflow paycom-census-export
```

Produces two files in `workflows/`:
- A Python script with numbered, commented steps
- A portable JSON workflow definition

Credentials are automatically parameterized — real values never appear in the output.

### Conversational Automation

You can also just describe what you want:

> "Scout the Paycom login page, log in with the credentials in .env, navigate to Census > Export, and download the CSV"

Claude will drive the browser step by step, scouting at each stage, and can export the workflow when done.

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

## Key Features

- **Anti-detection by default** — Botasaurus handles fingerprinting, timing, and stealth automatically
- **Secure credential injection** — `fill_secret` reads from `.env` server-side; values never appear in conversation
- **Full iframe + shadow DOM support** — Scout reports map the hierarchy; actions target elements in any context
- **Network monitoring** — Intercept XHR/API calls and downloads to reverse-engineer export workflows
- **Token-efficient** — Two-phase discovery: compact summary first (~200 tokens), drill into specifics on demand
- **Stateful sessions** — Login once, explore freely without re-authenticating

## License

MIT
