"""Browser Scout MCP Server — stealth browser reconnaissance for Claude Code."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Literal

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from .actions import execute_action
from .models import (
    ActionResult,
    FindElementsResult,
    MonitorResult,
    ScoutReport,
    SessionCloseResult,
    SessionHistory,
    SessionInfo,
)
from .scout import build_element_summary, filter_elements, scout_page
from .session import BrowserSession

# --- Application Context (lifespan-managed state) ---


@dataclass
class AppContext:
    """Holds all browser sessions across the server's lifetime."""

    sessions: dict[str, BrowserSession] = field(default_factory=dict)
    max_sessions: int = 1


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Initialize on startup, clean up all sessions on shutdown."""
    ctx = AppContext()
    try:
        yield ctx
    finally:
        for session in list(ctx.sessions.values()):
            try:
                await asyncio.to_thread(session.close)
            except Exception:
                pass


# --- MCP Server Instance ---

mcp = FastMCP("browser-scout", lifespan=app_lifespan)


def _get_ctx(ctx: Context) -> AppContext:
    return ctx.request_context.lifespan_context


def _get_session(app_ctx: AppContext, session_id: str) -> BrowserSession:
    session = app_ctx.sessions.get(session_id)
    if session is None:
        raise ValueError(f"No active session with id '{session_id}'. Use launch_session first.")
    if not session.is_active:
        raise ValueError(f"Session '{session_id}' is no longer active.")
    return session


# --- Tool: launch_session ---


@mcp.tool()
async def launch_session(
    url: str | None = None,
    headless: bool = False,
    proxy: str | None = None,
    download_dir: str = "./downloads",
    ctx: Context[ServerSession, AppContext] = None,
) -> dict:
    """Launch a new stealth browser session via Botasaurus with anti-detection enabled.

    The browser stays alive across all subsequent tool calls until close_session is called.
    Optionally navigate to an initial URL.

    Args:
        url: Initial URL to navigate to after launch. If omitted, opens a blank page.
        headless: Run browser in headless mode. Default: false (headed, for observation).
        proxy: Optional proxy URL (e.g., 'http://user:pass@host:port').
        download_dir: Directory for downloaded files. Default: './downloads'.
    """
    app_ctx = _get_ctx(ctx)

    if len(app_ctx.sessions) >= app_ctx.max_sessions:
        active_ids = list(app_ctx.sessions.keys())
        return {
            "error": f"Maximum sessions ({app_ctx.max_sessions}) reached. "
            f"Close session '{active_ids[0]}' first.",
            "active_sessions": active_ids,
        }

    session = BrowserSession(
        headless=headless,
        proxy=proxy,
        download_dir=download_dir,
    )

    await ctx.info(f"Launching browser session {session.session_id}...")
    info: SessionInfo = await asyncio.to_thread(session.launch, url)
    app_ctx.sessions[session.session_id] = session
    await ctx.info(f"Session {session.session_id} active at {info.current_url}")

    return info.model_dump(exclude_none=True)


# --- Tool: scout_page ---


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

    # Strip default/empty fields from each element for compact output
    stripped = []
    for el in matched:
        d = el.model_dump(exclude_none=True)
        # Strip true booleans that are default
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

    await ctx.info(f"Found {len(matched)} element(s) matching query")

    return {
        "matched": len(matched),
        "total_on_page": len(elements),
        "elements": stripped,
    }


# --- Tool: execute_action ---


@mcp.tool()
async def execute_action_tool(
    session_id: str,
    action: Literal["click", "type", "select", "navigate", "scroll", "wait", "press_key", "hover", "clear"],
    selector: str | None = None,
    value: str | None = None,
    frame_context: str | None = None,
    shadow_pierce: bool = False,
    wait_after: int = 500,
    ctx: Context[ServerSession, AppContext] = None,
) -> dict:
    """Perform a single interaction in the live browser session.

    Supports clicking, typing, selecting, navigating, scrolling, and waiting.
    Always scout after executing an action to observe the result.

    Args:
        session_id: Active session ID.
        action: The action to perform.
        selector: CSS selector of the target element. Required for click, type, select, hover, clear.
        value: Text to type, option to select, URL to navigate to, key to press, or wait duration.
        frame_context: Iframe selector path for the target element. Use 'main' or omit for top-level.
        shadow_pierce: Whether the selector needs shadow DOM piercing. Default: false.
        wait_after: Milliseconds to wait after action completes. Default: 500.
    """
    app_ctx = _get_ctx(ctx)
    session = _get_session(app_ctx, session_id)

    await ctx.info(f"Executing {action}...")
    result, record = await asyncio.to_thread(
        execute_action,
        session.driver,
        action,
        selector,
        value,
        frame_context,
        shadow_pierce,
        wait_after,
    )

    # Record in history
    session.history.record_action(record)
    if result.url_changed:
        session.history.record_navigation(result.current_url)

    # Invalidate element cache (DOM may have changed)
    session.invalidate_element_cache()

    if result.success:
        await ctx.info(f"Action complete: {result.action_performed}")
    else:
        await ctx.warning(f"Action failed: {result.error}")

    return result.model_dump(exclude_none=True)


# --- Tool: monitor_network ---


@mcp.tool()
async def monitor_network(
    session_id: str,
    command: Literal["start", "stop", "query", "wait_for_download"],
    url_pattern: str | None = None,
    timeout_ms: int = 30000,
    capture_response_body: bool = False,
    ctx: Context[ServerSession, AppContext] = None,
) -> dict:
    """Control network monitoring for the current session.

    Start monitoring before performing actions that trigger API calls or downloads,
    then query to see what was captured.

    Args:
        session_id: Active session ID.
        command: start: begin capturing. stop: stop. query: return captured events. wait_for_download: block until download.
        url_pattern: Optional regex pattern to filter captured requests by URL.
        timeout_ms: For wait_for_download: maximum wait time. Default: 30000.
        capture_response_body: Whether to capture response bodies (adds overhead). Default: false.
    """
    app_ctx = _get_ctx(ctx)
    session = _get_session(app_ctx, session_id)
    monitor = session.network_monitor

    match command:
        case "start":
            await ctx.info("Starting network monitoring...")
            await asyncio.to_thread(
                monitor.start, session.driver, url_pattern, capture_response_body
            )
            return MonitorResult(
                monitoring_active=True,
                total_captured=len(monitor.events),
            ).model_dump(exclude_none=True)

        case "stop":
            monitor.stop()
            await ctx.info("Network monitoring stopped.")
            return MonitorResult(
                monitoring_active=False,
                total_captured=len(monitor.events),
            ).model_dump(exclude_none=True)

        case "query":
            events = await asyncio.to_thread(monitor.query, url_pattern)
            # Record only new events in session history (avoid duplicates on repeated queries)
            existing_count = len(session.history.network_events)
            all_events = await asyncio.to_thread(monitor.query)
            for event in all_events[existing_count:]:
                session.history.record_network_event(event)
            return MonitorResult(
                events=events,
                total_captured=len(monitor.events),
                monitoring_active=monitor.monitoring,
            ).model_dump(exclude_none=True)

        case "wait_for_download":
            await ctx.info(f"Waiting for download (timeout: {timeout_ms}ms)...")
            download_events = await asyncio.to_thread(monitor.wait_for_download, timeout_ms)
            return MonitorResult(
                events=download_events,
                total_captured=len(monitor.events),
                monitoring_active=monitor.monitoring,
            ).model_dump(exclude_none=True)

        case _:
            return {"error": f"Unknown command: {command}"}


# --- Tool: get_session_history ---


@mcp.tool()
async def get_session_history(
    session_id: str,
    ctx: Context[ServerSession, AppContext] = None,
) -> dict:
    """Return the complete structured history of a browser session.

    Includes every action taken, every scout report (summarized), every network event
    captured, and the sequence of URLs visited. Use this data to compose Playwright scripts.

    Args:
        session_id: Active session ID.
    """
    app_ctx = _get_ctx(ctx)
    session = _get_session(app_ctx, session_id)

    history: SessionHistory = session.history.get_full_history()
    await ctx.info(
        f"Session history: {len(history.actions)} actions, "
        f"{len(history.scouts)} scouts, {len(history.network_events)} network events"
    )
    return history.model_dump(exclude_none=True)


# --- Tool: close_session ---


@mcp.tool()
async def close_session(
    session_id: str,
    ctx: Context[ServerSession, AppContext] = None,
) -> dict:
    """Close the browser session and release all resources.

    Always call this when automation exploration is complete.

    Args:
        session_id: Session ID to close.
    """
    app_ctx = _get_ctx(ctx)
    session = _get_session(app_ctx, session_id)

    await ctx.info(f"Closing session {session_id}...")
    result: SessionCloseResult = await asyncio.to_thread(session.close)
    del app_ctx.sessions[session_id]

    await ctx.info(
        f"Session closed. Duration: {result.session_duration_seconds}s, "
        f"Actions: {result.total_actions_performed}, Scouts: {result.total_scouts_performed}"
    )
    return result.model_dump(exclude_none=True)


# --- Entry Point ---


def main():
    """Run the MCP server via stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
