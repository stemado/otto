# Botasaurus Scout — MCP Server Design Document

## Part 1: Instructional Prompt (CLAUDE.md addition)

This is what Claude Code reads to understand how to use the tools effectively.

---

### Browser Automation Reconnaissance — Botasaurus Scout MCP

You have access to a live browser automation reconnaissance system via the `botasaurus-scout` MCP server. This system launches a stealth browser session (via Botasaurus, which handles anti-detection and fingerprint evasion) and lets you interactively explore websites through Chrome DevTools Protocol.

#### Philosophy

You are a **conversational automation architect**. Your job is to explore a target website interactively — navigating pages, inspecting structure, observing network behavior — and then produce a complete, production-grade Playwright script that handles everything the site is actually doing beneath the surface: nested iframes, shadow DOM, XHR interception, download events, authentication flows.

**Do not guess at page structure.** Always scout before generating code. Websites lie to you visually — the login form might be inside a triple-nested iframe behind a shadow DOM boundary. The export button might trigger an XHR that returns a signed URL rather than a direct download. Scout first, then compose.

#### Session Lifecycle — Critical

The browser session is **stateful and persistent**. It stays alive across all your tool calls until explicitly closed. This is not optional — it is an architectural requirement:

- **Login once.** Do not replay login sequences unnecessarily. Repeated rapid logins trigger security detection, CAPTCHAs, and account locks. Botasaurus gets you through the front door cleanly; don't announce yourself by opening and closing it repeatedly.
- **Scout after every significant action.** After clicking, navigating, or submitting a form, scout the page again. The DOM may have changed entirely — new iframes may have loaded, shadow DOM components may have mounted, network calls may have fired.
- **Build understanding incrementally.** Navigate step by step, scouting at each stage, exactly as a human developer would in DevTools. Your goal is to understand the complete workflow before generating any automation code.

#### Workflow Pattern

Follow this pattern for every automation task:

1. **Launch** — Start a session. Navigate to the target URL.
2. **Scout** — Inspect the page. Read the intelligence report carefully. Note iframe nesting, shadow DOM boundaries, form locations, and interactive elements.
3. **Act** — Execute a single interaction (click, type, select, navigate). 
4. **Scout again** — See what changed. New iframes? New network activity? Page transition?
5. **Repeat 3-4** — Continue through the entire workflow the user described.
6. **Monitor when needed** — Before actions that trigger downloads or API calls, start network monitoring. Then execute the action. Then check what was captured.
7. **Generate** — Once you've navigated the complete workflow and understand every step, compile the Playwright script. The script should encode everything you learned: correct frame contexts, proper selectors, network interception where needed, download handling, appropriate waits.

#### Reading Scout Reports

Scout reports return structured intelligence. Pay attention to:

- **`iframe_map`** — Shows nesting hierarchy. Each iframe entry includes its depth, src, and whether it's cross-origin. Cross-origin iframes cannot be inspected via DOM traversal; you'll need to navigate into them or use network interception.
- **`shadow_dom_boundaries`** — Lists elements with shadow roots. Selectors must pierce these boundaries. Playwright uses `>>` syntax for shadow DOM piercing.  
- **`interactive_elements`** — Buttons, links, inputs with their selectors and the frame context they live in. The frame context is critical — a selector is useless without knowing which iframe it belongs to.
- **`network_activity`** — Recent XHR/Fetch calls with URLs, methods, and response types. Patterns here reveal the actual API the UI is calling.
- **`page_metadata`** — Title, URL, load state. Verify you're on the page you expect after each navigation.

#### Generating Playwright Scripts

When you generate the final script:

- Use the **exact selectors** discovered during scouting, not guesses.
- Include **frame context switching** (`page.frameLocator()`) wherever elements live inside iframes.
- Add **network interception** (`page.route()` or `page.waitForResponse()`) for steps that depend on XHR/API calls.
- Use **download handling** (`page.waitForEvent('download')`) when the workflow captures files.
- Include **appropriate waits** — prefer waiting for specific elements or network events over arbitrary timeouts.
- Add **comments** explaining each section: what the step does and why the approach was chosen (e.g., "Login form is inside iframe#auth-frame > shadow-root > form, requiring frame context switch and shadow DOM piercing").
- Structure the script so it can run **independently** without the scout MCP — pure Playwright, no CDP dependencies.

#### What This System Cannot Do

- It cannot bypass CAPTCHAs (though Botasaurus reduces how often they appear).
- It cannot access cross-origin iframe content directly via DOM inspection. Use network monitoring or navigate to the iframe source URL separately if needed.
- It does not persist sessions between Claude Code conversations. Each conversation starts fresh.

---

## Part 2: MCP Tool Definitions

These are the tool schemas Claude Code receives when the MCP server connects.

---

### Tool: `launch_session`

**Description:** Launch a new stealth browser session via Botasaurus with anti-detection enabled. The browser stays alive across all subsequent tool calls until `close_session` is called. Optionally navigate to an initial URL. Returns a session ID and the browser's CDP endpoint for reference.

**Parameters:**
```json
{
  "url": {
    "type": "string",
    "description": "Optional. Initial URL to navigate to after launch. If omitted, opens a blank page.",
    "required": false
  },
  "headless": {
    "type": "boolean",
    "description": "Run browser in headless mode. Default: false (headed, useful for user observation during development).",
    "default": false
  },
  "proxy": {
    "type": "string", 
    "description": "Optional proxy URL (e.g., 'http://user:pass@host:port'). Botasaurus handles proxy integration.",
    "required": false
  }
}
```

**Returns:**
```json
{
  "session_id": "string — unique session identifier",
  "cdp_endpoint": "string — WebSocket URL (for reference, not direct use)",
  "browser_info": {
    "user_agent": "string — the fingerprinted user agent",
    "viewport": { "width": 1920, "height": 1080 }
  },
  "current_url": "string — the page URL after navigation (or about:blank)",
  "status": "active"
}
```

---

### Tool: `scout_page`

**Description:** Perform deep reconnaissance on the current page state. Returns a comprehensive intelligence report including DOM structure, iframe hierarchy (with nesting depth), shadow DOM boundaries, interactive elements with their frame contexts, and recent network activity. Call this after every significant navigation or interaction to understand what changed.

**Parameters:**
```json
{
  "session_id": {
    "type": "string",
    "description": "Active session ID from launch_session.",
    "required": true
  },
  "focus_frame": {
    "type": "string",
    "description": "Optional. Selector of a specific iframe to scout in detail rather than the full page. Useful for deep inspection of nested iframes.",
    "required": false
  },
  "include_network": {
    "type": "boolean",
    "description": "Include recent network activity (XHR/Fetch calls) in the report. Default: true.",
    "default": true
  },
  "include_styles": {
    "type": "boolean",
    "description": "Include computed visibility/display info for interactive elements. Adds token overhead but helps identify hidden elements. Default: false.",
    "default": false
  }
}
```

**Returns:**
```json
{
  "page_metadata": {
    "url": "string",
    "title": "string",
    "load_state": "string — domcontentloaded | load | networkidle"
  },
  "iframe_map": [
    {
      "selector": "string — CSS selector path to this iframe",
      "src": "string — iframe source URL",
      "depth": "number — nesting level (0 = top-level iframe)",
      "cross_origin": "boolean — whether this iframe is cross-origin",
      "children": ["array — nested iframes within this one"],
      "accessible": "boolean — whether DOM inspection is possible"
    }
  ],
  "shadow_dom_boundaries": [
    {
      "host_selector": "string — selector of the shadow host element",
      "mode": "string — open | closed",
      "frame_context": "string — which iframe this lives in, or 'main' for top-level",
      "child_interactive_count": "number — interactive elements inside this shadow root"
    }
  ],
  "interactive_elements": [
    {
      "tag": "string — element tag name",
      "type": "string — input type, button, link, select, etc.",
      "selector": "string — most reliable CSS selector",
      "text": "string — visible text content",
      "frame_context": "string — iframe selector path or 'main'",
      "in_shadow_dom": "boolean",
      "shadow_host": "string — host selector if in shadow DOM",
      "attributes": { "id": "", "name": "", "class": "", "href": "" },
      "visible": "boolean",
      "enabled": "boolean"
    }
  ],
  "network_activity": [
    {
      "url": "string",
      "method": "string — GET, POST, etc.",
      "type": "string — xhr, fetch, document, etc.",
      "status": "number — HTTP status code",
      "response_type": "string — json, blob, text, etc.",
      "timestamp": "string — ISO timestamp",
      "triggered_download": "boolean"
    }
  ],
  "page_summary": "string — human-readable summary of page structure for quick orientation"
}
```

---

### Tool: `execute_action`

**Description:** Perform a single interaction in the live browser session. Supports clicking, typing, selecting, navigating, scrolling, and waiting. Always scout after executing an action to observe the result. The action runs in the correct frame context if a frame_context is specified.

**Parameters:**
```json
{
  "session_id": {
    "type": "string",
    "description": "Active session ID.",
    "required": true
  },
  "action": {
    "type": "string",
    "enum": ["click", "type", "select", "navigate", "scroll", "wait", "press_key", "hover", "clear"],
    "description": "The action to perform.",
    "required": true
  },
  "selector": {
    "type": "string",
    "description": "CSS selector of the target element. Required for click, type, select, hover, clear.",
    "required": false
  },
  "value": {
    "type": "string",
    "description": "Text to type, option to select, URL to navigate to, key to press, or wait condition. Context-dependent on action type.",
    "required": false
  },
  "frame_context": {
    "type": "string",
    "description": "Iframe selector path for the target element (e.g., 'iframe#auth >>> iframe.inner'). Use 'main' or omit for top-level page. Obtained from scout_page results.",
    "required": false
  },
  "shadow_pierce": {
    "type": "boolean",
    "description": "Whether the selector needs to pierce shadow DOM boundaries. Default: false.",
    "default": false
  },
  "wait_after": {
    "type": "number",
    "description": "Milliseconds to wait after action completes before returning. Useful for allowing dynamic content to load. Default: 500.",
    "default": 500
  }
}
```

**Returns:**
```json
{
  "success": "boolean",
  "action_performed": "string — description of what was executed",
  "url_changed": "boolean — whether the page URL changed",
  "current_url": "string",
  "error": "string | null — error message if action failed",
  "elapsed_ms": "number — how long the action took"
}
```

---

### Tool: `monitor_network`

**Description:** Control network monitoring for the current session. Start monitoring before performing actions that trigger API calls or downloads, then query to see what was captured. Supports filtering by URL pattern, request type, or response content type.

**Parameters:**
```json
{
  "session_id": {
    "type": "string",
    "description": "Active session ID.",
    "required": true
  },
  "command": {
    "type": "string",
    "enum": ["start", "stop", "query", "wait_for_download"],
    "description": "start: begin capturing. stop: stop capturing. query: return captured events. wait_for_download: block until a download event is detected or timeout.",
    "required": true
  },
  "url_pattern": {
    "type": "string",
    "description": "Optional regex pattern to filter captured requests by URL. Only matching requests are retained.",
    "required": false
  },
  "timeout_ms": {
    "type": "number",
    "description": "For wait_for_download: maximum time to wait in milliseconds. Default: 30000.",
    "default": 30000
  },
  "capture_response_body": {
    "type": "boolean",
    "description": "Whether to capture response bodies. Increases data volume but necessary for inspecting API responses. Default: false.",
    "default": false
  }
}
```

**Returns (for query/wait_for_download):**
```json
{
  "events": [
    {
      "url": "string",
      "method": "string",
      "request_headers": {},
      "response_status": "number",
      "response_content_type": "string",
      "response_body": "string | null — if capture_response_body was true",
      "is_download": "boolean",
      "download_filename": "string | null",
      "download_size_bytes": "number | null",
      "timestamp": "string"
    }
  ],
  "total_captured": "number",
  "monitoring_active": "boolean"
}
```

---

### Tool: `generate_script`

**Description:** Compile the entire explored workflow into a standalone Playwright script. Uses all intelligence gathered from scouting and network monitoring throughout the session. The generated script is self-contained — it does not depend on this MCP server or CDP, only Playwright. Includes frame context switching, shadow DOM piercing, network interception, and download handling as needed.

**Parameters:**
```json
{
  "session_id": {
    "type": "string",
    "description": "Active session ID. The session's full action history and scout data are used to compose the script.",
    "required": true
  },
  "language": {
    "type": "string",
    "enum": ["python", "typescript", "csharp"],
    "description": "Target language for the Playwright script. Default: python.",
    "default": "python"
  },
  "include_comments": {
    "type": "boolean",
    "description": "Include detailed comments explaining each section. Default: true.",
    "default": true
  },
  "variable_extraction": {
    "type": "array",
    "items": { "type": "string" },
    "description": "List of values to extract as configurable variables (e.g., ['username', 'password', 'report_date']). These become parameters at the top of the script rather than hardcoded values.",
    "required": false
  },
  "output_path": {
    "type": "string",
    "description": "Optional file path to write the generated script to.",
    "required": false
  }
}
```

**Returns:**
```json
{
  "script": "string — the complete Playwright script",
  "steps_encoded": "number — how many workflow steps are in the script",
  "features_used": ["array — e.g., 'iframe_context_switching', 'shadow_dom_piercing', 'network_interception', 'download_handling'"],
  "warnings": ["array — any caveats, e.g., 'Step 4 uses a cross-origin iframe that could not be directly inspected; network interception used as fallback'"],
  "output_path": "string | null — file path if written to disk"
}
```

---

### Tool: `close_session`

**Description:** Close the browser session and release all resources. Always call this when the automation exploration is complete.

**Parameters:**
```json
{
  "session_id": {
    "type": "string",
    "description": "Session ID to close.",
    "required": true
  }
}
```

**Returns:**
```json
{
  "closed": true,
  "session_duration_seconds": "number",
  "total_actions_performed": "number",
  "total_scouts_performed": "number"
}
```