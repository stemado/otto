"""Data models for Browser Scout MCP server."""

from __future__ import annotations

from pydantic import BaseModel, Field


class IframeInfo(BaseModel):
    """Information about an iframe element on the page."""

    selector: str = Field(description="CSS selector path to this iframe")
    src: str = Field(default="", description="Iframe source URL")
    depth: int = Field(description="Nesting level (0 = top-level iframe)")
    cross_origin: bool = Field(default=False, description="Whether this iframe is cross-origin")
    accessible: bool = Field(default=True, description="Whether DOM inspection is possible")
    children: list[str] = Field(default_factory=list, description="Selectors of nested iframes")


class ShadowDomBoundary(BaseModel):
    """A shadow DOM boundary discovered on the page."""

    host_selector: str = Field(description="CSS selector of the shadow host element")
    mode: str = Field(description="Shadow root mode: 'open' or 'closed'")
    frame_context: str = Field(default="main", description="Iframe selector path or 'main'")
    child_interactive_count: int = Field(default=0, description="Interactive elements inside this shadow root")


class InteractiveElement(BaseModel):
    """An interactive element discovered during scouting."""

    tag: str = Field(description="Element tag name")
    type: str = Field(default="", description="Input type, button, link, select, etc.")
    selector: str = Field(description="Most reliable CSS selector")
    text: str = Field(default="", description="Visible text content")
    frame_context: str = Field(default="main", description="Iframe selector path or 'main'")
    in_shadow_dom: bool = Field(default=False)
    shadow_host: str | None = Field(default=None, description="Host selector if in shadow DOM")
    attributes: dict[str, str] = Field(default_factory=dict, description="Key attributes: id, name, class, href")
    visible: bool = Field(default=True)
    enabled: bool = Field(default=True)


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


class NetworkEvent(BaseModel):
    """A captured network request/response event."""

    url: str
    method: str = Field(default="GET")
    type: str = Field(default="other", description="xhr, fetch, document, etc.")
    status: int | None = Field(default=None, description="HTTP status code")
    response_type: str | None = Field(default=None, description="json, blob, text, etc.")
    timestamp: str = Field(description="ISO format timestamp")
    triggered_download: bool = Field(default=False)
    response_body: str | None = Field(default=None, description="Response body if captured, capped at 1MB")
    request_headers: dict[str, str] = Field(default_factory=dict)
    download_filename: str | None = Field(default=None)
    download_size_bytes: int | None = Field(default=None)


class PageMetadata(BaseModel):
    """Basic page state information."""

    url: str
    title: str
    load_state: str = Field(default="complete", description="domcontentloaded | load | networkidle")


class ScoutReport(BaseModel):
    """Comprehensive intelligence report from page scouting."""

    page_metadata: PageMetadata
    iframe_map: list[IframeInfo] = Field(default_factory=list)
    shadow_dom_boundaries: list[ShadowDomBoundary] = Field(default_factory=list)
    interactive_elements: list[InteractiveElement] = Field(default_factory=list)
    network_activity: list[NetworkEvent] = Field(default_factory=list)
    page_summary: str = Field(default="", description="Human-readable summary of page structure")


class ActionResult(BaseModel):
    """Result of executing a browser action."""

    success: bool
    action_performed: str = Field(description="Description of what was executed")
    url_changed: bool = Field(default=False)
    current_url: str = Field(default="")
    error: str | None = Field(default=None)
    elapsed_ms: int = Field(default=0)


class ActionRecord(BaseModel):
    """Historical record of an action taken during the session."""

    action: str
    selector: str | None = None
    value: str | None = None
    frame_context: str | None = None
    success: bool = True
    url_before: str = ""
    url_after: str = ""
    timestamp: str = ""
    error: str | None = None


class SessionInfo(BaseModel):
    """Information returned when a session is launched."""

    session_id: str
    cdp_endpoint: str | None = Field(default=None, description="WebSocket URL for reference")
    browser_info: dict = Field(default_factory=dict)
    current_url: str = Field(default="about:blank")
    status: str = Field(default="active")


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


class SessionHistory(BaseModel):
    """Complete structured history of a browser session."""

    session_id: str
    started_at: str
    actions: list[ActionRecord] = Field(default_factory=list)
    scouts: list[ScoutSummaryRecord] = Field(default_factory=list)
    find_elements_calls: list[FindElementsRecord] = Field(default_factory=list)
    network_events: list[NetworkEvent] = Field(default_factory=list)
    navigations: list[dict] = Field(default_factory=list, description="List of {url, timestamp}")


class SessionCloseResult(BaseModel):
    """Result of closing a session."""

    closed: bool = True
    session_duration_seconds: float = 0
    total_actions_performed: int = 0
    total_scouts_performed: int = 0


class MonitorResult(BaseModel):
    """Result from network monitoring operations."""

    events: list[NetworkEvent] = Field(default_factory=list)
    total_captured: int = 0
    monitoring_active: bool = False
