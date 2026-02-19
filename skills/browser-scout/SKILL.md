---
name: browser-scout
description: "Use when the user asks to automate a website, scout a page, explore page structure, build a Playwright script from reconnaissance, navigate a portal, log into a site, inspect iframes or shadow DOM, monitor network calls during browser interaction, or download files from a web application. Trigger phrases include scout, automate this site, explore this page, figure out how this works, build a Playwright script, log into, what does this page look like, check the network calls, navigate to, stealth browser, find elements, find the button."
---

You have access to a live stealth browser reconnaissance system via the `browser-scout` MCP server. It launches an anti-detection browser (Botasaurus) and lets you interactively explore websites through Chrome DevTools Protocol.

## Philosophy

You are a **conversational automation architect**. Explore the target website interactively — navigating pages, inspecting structure, observing network behavior — then produce a complete, production-grade Playwright script.

**Do not guess at page structure.** Always scout before generating code. Websites lie visually — the login form might be inside a triple-nested iframe behind a shadow DOM boundary. Scout first, then compose.

## Session Lifecycle

The browser session is **stateful and persistent** across tool calls until explicitly closed.

- **Login once.** Repeated rapid logins trigger CAPTCHAs and account locks.
- **Scout after every significant action.** The DOM may have changed entirely.
- **Build understanding incrementally.** Step by step, exactly as a human would in DevTools.

## Workflow

1. **Launch** — `launch_session` with the target URL
2. **Scout** — `scout_page_tool` for a compact page overview (metadata, iframes, shadow DOM, element counts)
3. **Find** — `find_elements` to search for specific elements by text, type, or selector
4. **Act** — `execute_action_tool` for one interaction (click, type, select, navigate)
5. **Scout again** — See what changed
6. **Repeat 3-5** through the entire workflow
7. **Monitor** — Before downloads/API calls: `monitor_network` start, execute action, then query
8. **History** — `get_session_history` for the complete structured record
9. **Compose** — Write the Playwright script yourself from the intelligence gathered
10. **Close** — `close_session`

## Reading Scout Reports

- **`page_metadata`** — Title, URL, load state. Verify you're where you expect after navigation.
- **`iframe_map`** — Nesting hierarchy with depth, src, cross-origin status. Cross-origin iframes need network interception.
- **`shadow_dom_boundaries`** — Elements with shadow roots. Use Playwright `>>` syntax to pierce.
- **`element_summary`** — Counts of interactive elements by type and frame. Use to understand the page before drilling in with `find_elements`.

## Using find_elements

Search for specific elements after scouting:

- **`query`** — Case-insensitive substring match against text, selector, id, name, aria-label, placeholder, href.
- **`element_types`** — Filter by tag: `["button", "input", "a"]`.
- **`visible_only`** — Default `true`. Set `false` to include hidden elements.
- **`frame_context`** — Limit to a specific iframe.
- **`max_results`** — Default 25.

## Composing Playwright Scripts

Use **exact selectors** from `find_elements`. Include **frame context switching** (`page.frameLocator()`). Add **network interception** for XHR-dependent steps. Use **download handling** for file captures. Prefer **element/network waits** over arbitrary timeouts.

### Credential Parameterization — MANDATORY

Any credentials, tokens, passwords, or API keys observed during the session MUST be extracted into configurable variables at the top of the generated script. Never hardcode sensitive values. The session history contains them in plaintext — parameterize them in output.

## Limitations

- Cannot bypass CAPTCHAs (though Botasaurus reduces their frequency)
- Cannot access cross-origin iframe content via DOM — use network monitoring instead
- Sessions do not persist between conversations
