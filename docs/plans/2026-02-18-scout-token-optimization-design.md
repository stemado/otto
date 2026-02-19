# Scout Token Optimization Design

**Date:** 2026-02-18
**Status:** Approved
**Problem:** A single `scout_page_tool` call returns ~11.8k tokens, mostly from serializing up to 500 interactive elements with empty fields. This fills context windows quickly and returns data before the model knows what it needs.

## Decision

Hybrid approach: slim down `scout_page_tool` to a structural overview, add a new `find_elements` tool for targeted element discovery, and apply cross-cutting cleanup to strip waste from all responses.

## Design

### 1. Slim `scout_page_tool`

The scout tool becomes a **structural overview** tool. It answers "what kind of page am I on?" without listing individual elements.

**Default response (new):**

```json
{
  "page_metadata": { "url": "...", "title": "...", "load_state": "complete" },
  "iframe_map": [],
  "shadow_dom_boundaries": [],
  "element_summary": {
    "total": 147,
    "visible": 120,
    "by_type": {
      "button": 12, "input": 8, "a": 45, "select": 3,
      "textarea": 1, "role_button": 5, "other": 73
    },
    "by_frame": { "main": 130, "iframe#content": 17 }
  },
  "page_summary": "Page: Job Scheduler (http://...) | 1 iframe | 0 shadow DOM | 147 interactive elements (120 visible)"
}
```

**Removed from default output:**
- `interactive_elements` array (moved to `find_elements`)
- `network_activity` (already available via `monitor_network`)

**Parameter changes:**
- Remove `include_network` parameter
- Keep `focus_frame` and `include_styles`
- Add `detail_level`: `"summary"` (default) | `"full"` (escape hatch, returns current behavior with empty fields stripped)

**Estimated token cost:** ~200-500 tokens (down from ~11,800).

### 2. New `find_elements` Tool

Targeted element discovery. Answers "where's the thing I need to interact with?"

**Signature:**

```python
find_elements(
    session_id: str,                    # required
    query: str = None,                  # text/selector search (e.g., "login", "#submit-btn")
    element_types: list[str] = None,    # filter by tag/role: ["button", "input", "a"]
    visible_only: bool = True,          # skip hidden elements by default
    frame_context: str = None,          # limit to specific iframe
    max_results: int = 25               # hard cap
)
```

**Query matching (Python-side, case-insensitive substring):**
- Matches against: `text`, `selector`, `attributes.id`, `attributes.name`, `attributes.aria_label`, `attributes.placeholder`, `attributes.href`
- If query looks like a CSS selector (starts with `#`, `.`, or contains `[`), also try exact selector match

**Response format:**

```json
{
  "matched": 3,
  "total_on_page": 147,
  "elements": [
    {
      "tag": "button",
      "type": "submit",
      "selector": "#login-btn",
      "text": "Log In",
      "frame_context": "main",
      "attributes": { "id": "login-btn", "class": "btn-primary" }
    }
  ]
}
```

**Field stripping rules:**
- Empty attribute values omitted (no `"name": ""`)
- `in_shadow_dom` / `shadow_host` only included when `true` / present
- `visible` / `enabled` only included when `false` (since `visible_only=True` default means most results are visible)

**Implementation:**
- JS collects all elements (same `scout_page.js`)
- Python filters by query/element_types/visible_only/frame_context, caps at max_results, strips empties
- Element data cached on `BrowserSession`, invalidated on navigation or action

**Estimated token cost:** ~100-800 tokens for typical queries.

### 3. Cross-Cutting Cleanup

#### 3a. JavaScript: Strip empty attributes at source

In `scout_page.js`, only include attribute keys with non-empty values:

```javascript
// Only include non-empty values
const attrs = {};
if (el.id) attrs.id = el.id;
if (el.getAttribute("name")) attrs.name = el.getAttribute("name");
// ...
```

#### 3b. Python: `model_dump(exclude_none=True)`

Every tool response serializing a Pydantic model uses `exclude_none=True` to strip null fields.

#### 3c. Session history: summarize past scouts

`get_session_history` stores summary-level scout reports (not full element lists). `find_elements` results recorded as compact entries:

```json
{"action": "find_elements", "query": "login", "matched": 3}
```

#### 3d. `detail_level="full"` escape hatch

When `scout_page_tool(detail_level="full")`:
- Returns current full output with empty fields stripped (3a + 3b applied)
- Estimated ~30-40% reduction from stripping alone
- Exists for edge cases where everything is needed in one call

## Token Budget Comparison

| Scenario | Before | After |
|----------|--------|-------|
| Initial page scout | ~11,800 | ~200-500 |
| Find a specific button | N/A (included in scout) | ~100-300 |
| Scout + find element | ~11,800 | ~300-800 |
| Full page dump (escape hatch) | ~11,800 | ~7,000-8,000 |
| 5-page session history | ~60,000+ | ~2,500-5,000 |

## Files to Modify

| File | Changes |
|------|---------|
| `src/browser_scout/server.py` | Modify `scout_page_tool` handler, add `find_elements` tool, apply `exclude_none=True` |
| `src/browser_scout/scout.py` | Add element summary generation, element filtering/query logic, caching |
| `src/browser_scout/models.py` | Add `ElementSummary` model, `FindElementsResult` model |
| `src/browser_scout/js/scout_page.js` | Strip empty attributes in JS |
| `src/browser_scout/history.py` | Store summary-level scouts, compact find_elements entries |
| `CLAUDE.md` | Update tool documentation to reflect new workflow |
| `skills/browser-scout/SKILL.md` | Update skill trigger to mention `find_elements` |

## Unchanged

- `execute_action_tool` — unchanged
- `monitor_network` — unchanged
- `close_session` — unchanged
- `launch_session` — unchanged
