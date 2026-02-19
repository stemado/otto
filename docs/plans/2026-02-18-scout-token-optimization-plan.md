# Scout Token Optimization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce scout_page_tool token output from ~11.8k to ~200-500 by splitting into a compact structural overview + targeted find_elements tool, with empty field stripping across all responses.

**Architecture:** Hybrid approach — slim scout returns page structure + element counts (no element list), new find_elements tool for targeted queries with caching. JS strips empty attributes at source, Python applies exclude_none on all model_dump calls. History stores summary-level scouts only.

**Tech Stack:** Python 3.11+, Pydantic v2, botasaurus-driver, mcp[cli], pytest

---

### Task 1: Strip Empty Attributes in JavaScript

**Files:**
- Modify: `src/browser_scout/js/scout_page.js:185-204`

**Step 1: Modify the attributes object construction**

Replace the attributes block in `findInteractiveElements` (lines 193-201) from always-include to conditional-include:

```javascript
      // Build attributes — only include non-empty values
      const attrs = {};
      if (el.id) attrs.id = el.id;
      if (el.name) attrs.name = el.name;
      if (el.className) attrs.class = el.className;
      const href = el.href || el.getAttribute("href");
      if (href) attrs.href = href;
      if (el.placeholder) attrs.placeholder = el.placeholder;
      if (el.tagName === "INPUT" && el.type !== "password" && el.value) {
        attrs.value = el.value;
      }
      const ariaLabel = el.getAttribute("aria-label");
      if (ariaLabel) attrs.aria_label = ariaLabel;
```

**Step 2: Verify the change is syntactically valid**

Run: `node -c src/browser_scout/js/scout_page.js` (This will fail because the file is a function body, not standalone. Instead, wrap it:)

Run: `node -e "const f = new Function(require('fs').readFileSync('src/browser_scout/js/scout_page.js','utf8')); console.log('JS syntax OK')"`

Expected: "JS syntax OK" (no syntax errors)

**Step 3: Commit**

```bash
git add src/browser_scout/js/scout_page.js
git commit -m "refactor(js): strip empty attributes at source

Only include attribute keys with non-empty values in scout_page.js.
Eliminates serialization of empty strings like id:'', name:'', href:''
which were inflating scout report token counts."
```

---

### Task 2: Add New Pydantic Models

**Files:**
- Modify: `src/browser_scout/models.py`
- Create: `tests/test_models.py`

**Step 1: Write failing tests for new models**

```python
"""Tests for new token-optimization models."""
import pytest
from browser_scout.models import ElementSummary, FindElementsResult, InteractiveElement


def test_element_summary_creation():
    summary = ElementSummary(
        total=100,
        visible=80,
        by_type={"button": 10, "input": 5, "a": 65},
        by_frame={"main": 90, "iframe#content": 10},
    )
    assert summary.total == 100
    assert summary.visible == 80
    assert summary.by_type["button"] == 10
    assert summary.by_frame["main"] == 90


def test_element_summary_defaults():
    summary = ElementSummary(total=0, visible=0)
    assert summary.by_type == {}
    assert summary.by_frame == {}


def test_find_elements_result():
    result = FindElementsResult(
        matched=2,
        total_on_page=50,
        elements=[
            InteractiveElement(
                tag="button",
                type="submit",
                selector="#login",
                text="Log In",
            ),
        ],
    )
    assert result.matched == 2
    assert len(result.elements) == 1
    assert result.elements[0].selector == "#login"


def test_find_elements_result_defaults():
    result = FindElementsResult(matched=0, total_on_page=0)
    assert result.elements == []
```

**Step 2: Run tests to verify they fail**

Run: `cd d:/Projects/browser-scout && uv run pytest tests/test_models.py -v`

Expected: FAIL — `ImportError: cannot import name 'ElementSummary'` and `cannot import name 'FindElementsResult'`

**Step 3: Add the new models to models.py**

Add after the `InteractiveElement` class (around line 41):

```python
class ElementSummary(BaseModel):
    """Aggregated summary of interactive elements on a page."""

    total: int = Field(description="Total interactive elements found")
    visible: int = Field(description="Number of visible interactive elements")
    by_type: dict[str, int] = Field(default_factory=dict, description="Count by element type")
    by_frame: dict[str, int] = Field(default_factory=dict, description="Count by frame context")


class FindElementsResult(BaseModel):
    """Result from targeted element search."""

    matched: int = Field(description="Number of elements matching the query")
    total_on_page: int = Field(description="Total interactive elements on the page")
    elements: list[InteractiveElement] = Field(default_factory=list)
```

**Step 4: Run tests to verify they pass**

Run: `cd d:/Projects/browser-scout && uv run pytest tests/test_models.py -v`

Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add src/browser_scout/models.py tests/test_models.py
git commit -m "feat(models): add ElementSummary and FindElementsResult

New Pydantic models for the token optimization:
- ElementSummary: aggregated counts by type/frame for compact scout output
- FindElementsResult: wrapper for targeted element search responses"
```

---

### Task 3: Element Summary Generation and Query/Filter Logic

**Files:**
- Modify: `src/browser_scout/scout.py`
- Create: `tests/test_scout_filters.py`

**Step 1: Write failing tests for element summary generation**

```python
"""Tests for element summary generation and query/filter logic."""
import pytest
from browser_scout.models import InteractiveElement, ElementSummary
from browser_scout.scout import build_element_summary, filter_elements


def _make_element(
    tag="button", type_="button", selector="#btn", text="Click",
    frame_context="main", visible=True, enabled=True,
    in_shadow_dom=False, shadow_host=None, attributes=None,
):
    return InteractiveElement(
        tag=tag, type=type_, selector=selector, text=text,
        frame_context=frame_context, visible=visible, enabled=enabled,
        in_shadow_dom=in_shadow_dom, shadow_host=shadow_host,
        attributes=attributes or {},
    )


class TestBuildElementSummary:
    def test_empty_list(self):
        summary = build_element_summary([])
        assert summary.total == 0
        assert summary.visible == 0
        assert summary.by_type == {}
        assert summary.by_frame == {}

    def test_counts_by_type(self):
        elements = [
            _make_element(tag="button", type_="button"),
            _make_element(tag="button", type_="submit"),
            _make_element(tag="input", type_="text"),
            _make_element(tag="a", type_="a"),
        ]
        summary = build_element_summary(elements)
        assert summary.total == 4
        assert summary.by_type["button"] == 2
        assert summary.by_type["input"] == 1
        assert summary.by_type["a"] == 1

    def test_counts_by_frame(self):
        elements = [
            _make_element(frame_context="main"),
            _make_element(frame_context="main"),
            _make_element(frame_context="iframe#content"),
        ]
        summary = build_element_summary(elements)
        assert summary.by_frame["main"] == 2
        assert summary.by_frame["iframe#content"] == 1

    def test_visible_count(self):
        elements = [
            _make_element(visible=True),
            _make_element(visible=False),
            _make_element(visible=True),
        ]
        summary = build_element_summary(elements)
        assert summary.visible == 2


class TestFilterElements:
    def test_no_filters_returns_all(self):
        elements = [_make_element(text="A"), _make_element(text="B")]
        result = filter_elements(elements)
        assert len(result) == 2

    def test_query_matches_text(self):
        elements = [
            _make_element(text="Login"),
            _make_element(text="Submit"),
            _make_element(text="Log Out"),
        ]
        result = filter_elements(elements, query="log")
        assert len(result) == 2
        assert result[0].text == "Login"
        assert result[1].text == "Log Out"

    def test_query_matches_id_attribute(self):
        elements = [
            _make_element(text="Go", attributes={"id": "login-btn"}),
            _make_element(text="Go", attributes={"id": "submit-btn"}),
        ]
        result = filter_elements(elements, query="login")
        assert len(result) == 1

    def test_query_matches_aria_label(self):
        elements = [
            _make_element(text="", attributes={"aria_label": "Close dialog"}),
            _make_element(text="OK"),
        ]
        result = filter_elements(elements, query="close")
        assert len(result) == 1

    def test_query_matches_placeholder(self):
        elements = [
            _make_element(tag="input", text="", attributes={"placeholder": "Enter email"}),
        ]
        result = filter_elements(elements, query="email")
        assert len(result) == 1

    def test_query_matches_selector(self):
        elements = [
            _make_element(selector="#login-form > button"),
            _make_element(selector="#nav > a"),
        ]
        result = filter_elements(elements, query="#login-form")
        assert len(result) == 1

    def test_element_types_filter(self):
        elements = [
            _make_element(tag="button"),
            _make_element(tag="input"),
            _make_element(tag="a"),
        ]
        result = filter_elements(elements, element_types=["button", "a"])
        assert len(result) == 2

    def test_visible_only(self):
        elements = [
            _make_element(visible=True),
            _make_element(visible=False),
        ]
        result = filter_elements(elements, visible_only=True)
        assert len(result) == 1

    def test_visible_only_false(self):
        elements = [
            _make_element(visible=True),
            _make_element(visible=False),
        ]
        result = filter_elements(elements, visible_only=False)
        assert len(result) == 2

    def test_frame_context_filter(self):
        elements = [
            _make_element(frame_context="main"),
            _make_element(frame_context="iframe#sidebar"),
        ]
        result = filter_elements(elements, frame_context="iframe#sidebar")
        assert len(result) == 1

    def test_max_results(self):
        elements = [_make_element(text=f"Btn {i}") for i in range(50)]
        result = filter_elements(elements, max_results=10)
        assert len(result) == 10

    def test_combined_filters(self):
        elements = [
            _make_element(tag="button", text="Login", visible=True, frame_context="main"),
            _make_element(tag="button", text="Login", visible=False, frame_context="main"),
            _make_element(tag="input", text="Username", visible=True, frame_context="main"),
            _make_element(tag="button", text="Login", visible=True, frame_context="iframe#modal"),
        ]
        result = filter_elements(
            elements, query="login", element_types=["button"],
            visible_only=True, frame_context="main",
        )
        assert len(result) == 1
        assert result[0].text == "Login"
        assert result[0].visible is True
```

**Step 2: Run tests to verify they fail**

Run: `cd d:/Projects/browser-scout && uv run pytest tests/test_scout_filters.py -v`

Expected: FAIL — `ImportError: cannot import name 'build_element_summary'` and `'filter_elements'`

**Step 3: Implement build_element_summary and filter_elements in scout.py**

Add these functions at the end of `scout.py` (before `_error_report`):

```python
def build_element_summary(elements: list[InteractiveElement]) -> ElementSummary:
    """Build an aggregated summary from a list of interactive elements."""
    by_type: dict[str, int] = {}
    by_frame: dict[str, int] = {}
    visible = 0

    for el in elements:
        # Count by tag (use tag as the grouping key)
        by_type[el.tag] = by_type.get(el.tag, 0) + 1
        # Count by frame
        by_frame[el.frame_context] = by_frame.get(el.frame_context, 0) + 1
        if el.visible:
            visible += 1

    return ElementSummary(
        total=len(elements),
        visible=visible,
        by_type=by_type,
        by_frame=by_frame,
    )


def filter_elements(
    elements: list[InteractiveElement],
    query: str | None = None,
    element_types: list[str] | None = None,
    visible_only: bool = True,
    frame_context: str | None = None,
    max_results: int = 25,
) -> list[InteractiveElement]:
    """Filter interactive elements by query, type, visibility, and frame.

    Args:
        elements: Full list of interactive elements from a scout.
        query: Case-insensitive substring match against text, selector, and key attributes.
        element_types: Filter to only these tag names (e.g., ["button", "input"]).
        visible_only: If True, exclude hidden elements.
        frame_context: If set, only return elements in this frame.
        max_results: Maximum number of elements to return.
    """
    results = elements

    if visible_only:
        results = [el for el in results if el.visible]

    if element_types:
        type_set = {t.lower() for t in element_types}
        results = [el for el in results if el.tag.lower() in type_set]

    if frame_context:
        results = [el for el in results if el.frame_context == frame_context]

    if query:
        q = query.lower()
        filtered = []
        for el in results:
            searchable = [
                el.text,
                el.selector,
                el.attributes.get("id", ""),
                el.attributes.get("name", ""),
                el.attributes.get("aria_label", ""),
                el.attributes.get("placeholder", ""),
                el.attributes.get("href", ""),
            ]
            if any(q in field.lower() for field in searchable if field):
                filtered.append(el)
        results = filtered

    return results[:max_results]
```

Also add the import at the top of `scout.py`:

```python
from .models import (
    ElementSummary,
    ...existing imports...
)
```

**Step 4: Run tests to verify they pass**

Run: `cd d:/Projects/browser-scout && uv run pytest tests/test_scout_filters.py -v`

Expected: All 16 tests PASS

**Step 5: Commit**

```bash
git add src/browser_scout/scout.py tests/test_scout_filters.py
git commit -m "feat(scout): add element summary generation and query filtering

- build_element_summary(): aggregates element counts by type and frame
- filter_elements(): case-insensitive query matching against text,
  selector, id, name, aria_label, placeholder, href; supports
  element_types, visible_only, frame_context, and max_results filters"
```

---

### Task 4: Element Caching on BrowserSession

**Files:**
- Modify: `src/browser_scout/session.py`

**Step 1: Add element cache fields to BrowserSession**

Add after `self.network_monitor = NetworkMonitor(self.download_dir)` in `__init__`:

```python
        # Cached elements from the most recent scout (invalidated on action/navigation)
        self._cached_elements: list[InteractiveElement] | None = None
```

Add cache methods:

```python
    def cache_elements(self, elements: list[InteractiveElement]) -> None:
        """Cache elements from a scout for use by find_elements."""
        self._cached_elements = elements

    def get_cached_elements(self) -> list[InteractiveElement] | None:
        """Return cached elements, or None if cache is empty/invalidated."""
        return self._cached_elements

    def invalidate_element_cache(self) -> None:
        """Invalidate the element cache (call after actions/navigations)."""
        self._cached_elements = None
```

Add the import at the top:

```python
from .models import InteractiveElement, SessionCloseResult, SessionInfo
```

**Step 2: Commit**

```bash
git add src/browser_scout/session.py
git commit -m "feat(session): add element cache for find_elements

Cache scout results on BrowserSession so find_elements can query
without re-injecting JS. Cache invalidated on actions/navigation."
```

---

### Task 5: Update History Tracker for Summary-Level Storage

**Files:**
- Modify: `src/browser_scout/history.py`
- Modify: `src/browser_scout/models.py`

**Step 1: Add ScoutSummaryRecord and FindElementsRecord models**

Add to `models.py`:

```python
class ScoutSummaryRecord(BaseModel):
    """Compact scout record for session history (no element list)."""

    page_metadata: PageMetadata
    iframe_count: int = 0
    shadow_dom_count: int = 0
    element_summary: ElementSummary | None = None
    page_summary: str = ""


class FindElementsRecord(BaseModel):
    """Compact record of a find_elements call for session history."""

    query: str | None = None
    element_types: list[str] | None = None
    matched: int = 0
    timestamp: str = ""
```

Update `SessionHistory` to use `ScoutSummaryRecord` instead of `ScoutReport`:

```python
class SessionHistory(BaseModel):
    """Complete structured history of a browser session."""

    session_id: str
    started_at: str
    actions: list[ActionRecord] = Field(default_factory=list)
    scouts: list[ScoutSummaryRecord] = Field(default_factory=list)
    find_elements_calls: list[FindElementsRecord] = Field(default_factory=list)
    network_events: list[NetworkEvent] = Field(default_factory=list)
    navigations: list[dict] = Field(default_factory=list, description="List of {url, timestamp}")
```

**Step 2: Update SessionHistoryTracker in history.py**

Replace `record_scout` to store summary-level records, and add `record_find_elements`:

```python
from .models import (
    ActionRecord,
    FindElementsRecord,
    NetworkEvent,
    ScoutReport,
    ScoutSummaryRecord,
    SessionHistory,
)
from .scout import build_element_summary


class SessionHistoryTracker:
    """Tracks all actions, scout reports, network events, and navigations for a session."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.actions: list[ActionRecord] = []
        self.scouts: list[ScoutSummaryRecord] = []
        self.find_elements_calls: list[FindElementsRecord] = []
        self.network_events: list[NetworkEvent] = []
        self.navigations: list[dict] = []

    def record_scout(self, report: ScoutReport) -> None:
        """Record a compact summary of a scout (no element list)."""
        summary = build_element_summary(report.interactive_elements)
        self.scouts.append(ScoutSummaryRecord(
            page_metadata=report.page_metadata,
            iframe_count=len(report.iframe_map),
            shadow_dom_count=len(report.shadow_dom_boundaries),
            element_summary=summary,
            page_summary=report.page_summary,
        ))

    def record_find_elements(self, query: str | None, element_types: list[str] | None, matched: int) -> None:
        """Record a compact find_elements call."""
        self.find_elements_calls.append(FindElementsRecord(
            query=query,
            element_types=element_types,
            matched=matched,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ))

    def record_action(self, record: ActionRecord) -> None:
        self.actions.append(record)

    def record_navigation(self, url: str) -> None:
        self.navigations.append({
            "url": url,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def record_network_event(self, event: NetworkEvent) -> None:
        self.network_events.append(event)

    def get_full_history(self) -> SessionHistory:
        return SessionHistory(
            session_id=self.session_id,
            started_at=self.started_at,
            actions=self.actions,
            scouts=self.scouts,
            find_elements_calls=self.find_elements_calls,
            network_events=self.network_events,
            navigations=self.navigations,
        )
```

**Step 3: Commit**

```bash
git add src/browser_scout/models.py src/browser_scout/history.py
git commit -m "feat(history): store summary-level scout records

History now stores ScoutSummaryRecord (metadata + counts, no element
list) instead of full ScoutReport. Adds FindElementsRecord for
compact tracking of find_elements calls. Prevents history from
growing multiplicatively with each scout."
```

---

### Task 6: Wire Up server.py — Modify scout_page_tool + Add find_elements

**Files:**
- Modify: `src/browser_scout/server.py`

**Step 1: Update imports in server.py**

```python
from .models import (
    ActionResult,
    ElementSummary,
    FindElementsResult,
    MonitorResult,
    ScoutReport,
    SessionCloseResult,
    SessionHistory,
    SessionInfo,
)
from .scout import build_element_summary, filter_elements, scout_page
```

**Step 2: Modify scout_page_tool**

Replace the entire `scout_page_tool` function (lines 119-155):

```python
@mcp.tool()
async def scout_page_tool(
    session_id: str,
    focus_frame: str | None = None,
    include_styles: bool = False,
    detail_level: Literal["summary", "full"] = "summary",
    ctx: Context[ServerSession, AppContext] = None,
) -> dict:
    """Perform deep reconnaissance on the current page state.

    Returns a structural overview of the page: metadata, iframe hierarchy,
    shadow DOM boundaries, and element counts. Use find_elements to search
    for specific interactive elements by text, type, or selector.

    Args:
        session_id: Active session ID from launch_session.
        focus_frame: Optional iframe CSS selector to scout instead of the full page.
        include_styles: Include computed visibility info for elements. Default: false.
        detail_level: 'summary' (default) returns compact overview with element counts.
                      'full' returns all interactive elements (large response).
    """
    app_ctx = _get_ctx(ctx)
    session = _get_session(app_ctx, session_id)

    await ctx.info("Scouting page...")
    report: ScoutReport = await asyncio.to_thread(
        scout_page, session.driver, focus_frame, include_styles
    )

    # Cache elements for find_elements queries
    session.cache_elements(report.interactive_elements)

    # Record in history (always stores summary-level)
    session.history.record_scout(report)

    await ctx.info(f"Scout complete: {report.page_summary}")

    if detail_level == "full":
        return report.model_dump(exclude_none=True)

    # Summary mode: return structure + counts, no element list
    element_summary = build_element_summary(report.interactive_elements)
    return {
        "page_metadata": report.page_metadata.model_dump(exclude_none=True),
        "iframe_map": [f.model_dump(exclude_none=True) for f in report.iframe_map],
        "shadow_dom_boundaries": [s.model_dump(exclude_none=True) for s in report.shadow_dom_boundaries],
        "element_summary": element_summary.model_dump(exclude_none=True),
        "page_summary": report.page_summary,
    }
```

**Step 3: Add find_elements tool**

Add after `scout_page_tool` and before `execute_action_tool`:

```python
# --- Tool: find_elements ---


@mcp.tool()
async def find_elements(
    session_id: str,
    query: str | None = None,
    element_types: list[str] | None = None,
    visible_only: bool = True,
    frame_context: str | None = None,
    max_results: int = 25,
    ctx: Context[ServerSession, AppContext] = None,
) -> dict:
    """Search for specific interactive elements on the current page.

    Returns matching elements with selectors, text, and attributes.
    Call scout_page_tool first to cache the page structure, then use this
    tool to find specific elements by text, type, or CSS selector.

    Args:
        session_id: Active session ID.
        query: Text or selector to search for (case-insensitive substring match).
               Matches against element text, selector, id, name, aria-label, placeholder, href.
        element_types: Filter by tag name, e.g. ['button', 'input', 'a'].
        visible_only: Only return visible elements. Default: true.
        frame_context: Limit search to a specific iframe (use selector from scout report).
        max_results: Maximum elements to return. Default: 25.
    """
    app_ctx = _get_ctx(ctx)
    session = _get_session(app_ctx, session_id)

    # Use cached elements or re-scout if cache is empty
    elements = session.get_cached_elements()
    if elements is None:
        await ctx.info("No cached elements — scouting page first...")
        report: ScoutReport = await asyncio.to_thread(
            scout_page, session.driver, None, False
        )
        elements = report.interactive_elements
        session.cache_elements(elements)
        session.history.record_scout(report)

    matched = filter_elements(
        elements,
        query=query,
        element_types=element_types,
        visible_only=visible_only,
        frame_context=frame_context,
        max_results=max_results,
    )

    # Record in history
    session.history.record_find_elements(query, element_types, len(matched))

    # Strip empty fields from each element
    stripped = []
    for el in matched:
        d = el.model_dump(exclude_none=True)
        # Strip false booleans that are default (visible=True, enabled=True, in_shadow_dom=False)
        if d.get("visible") is True:
            del d["visible"]
        if d.get("enabled") is True:
            del d["enabled"]
        if d.get("in_shadow_dom") is False:
            del d["in_shadow_dom"]
        # Strip empty text
        if not d.get("text"):
            d.pop("text", None)
        # Strip empty attributes dict
        if not d.get("attributes"):
            d.pop("attributes", None)
        # Strip default frame_context
        if d.get("frame_context") == "main":
            del d["frame_context"]
        stripped.append(d)

    result = FindElementsResult(
        matched=len(matched),
        total_on_page=len(elements),
        elements=matched,
    )

    await ctx.info(f"Found {len(matched)} element(s) matching query")

    # Return the stripped version directly (not via model_dump to preserve stripping)
    return {
        "matched": len(matched),
        "total_on_page": len(elements),
        "elements": stripped,
    }
```

**Step 4: Add cache invalidation in execute_action_tool**

In `execute_action_tool`, after `session.history.record_action(record)` (around line 202), add:

```python
    # Invalidate element cache (DOM may have changed)
    session.invalidate_element_cache()
```

**Step 5: Apply exclude_none=True to remaining tool responses**

In `launch_session` return (line 113):
```python
    return info.model_dump(exclude_none=True)
```

In `execute_action_tool` return (line 211):
```python
    return result.model_dump(exclude_none=True)
```

In `monitor_network` — all MonitorResult returns (lines 248-251, 253-256, 268-272, 277-281):
```python
    # Add exclude_none=True to all .model_dump() calls in monitor_network
```

In `get_session_history` return (line 311):
```python
    return history.model_dump(exclude_none=True)
```

In `close_session` return (line 340):
```python
    return result.model_dump(exclude_none=True)
```

**Step 6: Commit**

```bash
git add src/browser_scout/server.py
git commit -m "feat(server): slim scout_page_tool, add find_elements tool

- scout_page_tool now returns compact summary by default (~200-500 tokens)
  with detail_level='full' escape hatch
- New find_elements tool for targeted element search with query matching,
  type filtering, visibility filtering, and frame context scoping
- Element cache on session, invalidated on actions
- exclude_none=True applied to all model_dump() calls
- Removes include_network parameter (use monitor_network separately)"
```

---

### Task 7: Update Documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `skills/browser-scout/SKILL.md`
- Modify: `commands/scout.md`

**Step 1: Update CLAUDE.md**

Key changes:
- Update workflow pattern: scout returns summary, use `find_elements` for targeted search
- Update "Reading Scout Reports" to describe new `element_summary` field instead of `interactive_elements`
- Remove `interactive_elements` and `network_activity` from scout report description
- Add `find_elements` tool documentation
- Update limitations (remove "capped at 500" since elements are no longer in scout output)

**Step 2: Update SKILL.md**

Update workflow section to include `find_elements` in the tool list and workflow pattern.

**Step 3: Update commands/scout.md**

Update step 2 to reflect that scout returns a compact summary, and optionally call `find_elements` to list key elements.

**Step 4: Commit**

```bash
git add CLAUDE.md skills/browser-scout/SKILL.md commands/scout.md
git commit -m "docs: update tool documentation for token-optimized workflow

Reflects new scout_page_tool (summary default) and find_elements tool.
Updates workflow pattern, scout report descriptions, and limitations."
```

---

### Task 8: Run All Tests and Verify

**Step 1: Run the full test suite**

Run: `cd d:/Projects/browser-scout && uv run pytest tests/ -v`

Expected: All tests PASS

**Step 2: Verify the MCP server starts**

Run: `cd d:/Projects/browser-scout && uv run browser-scout 2>&1 | head -5`

Expected: Server starts without import errors (will block on stdin — Ctrl+C to exit)

**Step 3: Commit any fixes if needed**

---

### Task 9: Manual Integration Test

**Step 1: Test via Claude Code**

Use the plugin to:
1. Launch a session with a URL
2. Call `scout_page_tool` — verify response is ~200-500 tokens (compact summary)
3. Call `find_elements` with a query — verify targeted results
4. Call `scout_page_tool` with `detail_level="full"` — verify full report (with stripped empties)
5. Call `get_session_history` — verify compact history records
6. Close session

**Step 2: Document results in design doc review section**
