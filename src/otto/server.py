"""Otto MCP Server — stealth browser automation for Claude Code."""

from __future__ import annotations

import asyncio
import atexit
import re
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Literal

import base64
import json

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from mcp.types import CallToolResult, ImageContent, TextContent

from .actions import execute_action, inspect_element, run_javascript, take_screenshot
from .models import (
    ActionRecord,
    FillSecretResult,
    MonitorResult,
    RecordingRecord,
    RecordingResult,
    ScoutReport,
    SessionCloseResult,
    SessionHistory,
    SessionInfo,
)
from .secrets import EnvLoadError, load_env_vars
from .sanitize import sanitize_response
from .scout import build_element_summary, filter_elements, scout_page
from .session import BrowserSession

# --- Numeric safety bounds ---

MAX_WAIT_MS = 60_000        # 1 minute
MAX_TIMEOUT_MS = 300_000    # 5 minutes
MAX_RESULTS = 500           # Scout JS caps at 500 elements

# --- Session ID format ---

_SESSION_ID_RE = re.compile(r"^[0-9a-f]{12}$")

# --- Application Context (lifespan-managed state) ---


@dataclass
class AppContext:
    """Holds all browser sessions across the server's lifetime."""

    sessions: dict[str, BrowserSession] = field(default_factory=dict)
    max_sessions: int = 1
    env_vars: dict[str, str] | None = field(default=None)
    _launch_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Initialize on startup, clean up all sessions on shutdown."""
    ctx = AppContext()

    def _cleanup_sync():
        """Emergency cleanup for atexit handler."""
        for session in list(ctx.sessions.values()):
            try:
                session.close()
            except Exception:
                pass

    atexit.register(_cleanup_sync)

    try:
        yield ctx
    finally:
        atexit.unregister(_cleanup_sync)
        for session in list(ctx.sessions.values()):
            try:
                await asyncio.to_thread(session.close)
            except Exception:
                pass


# --- MCP Server Instance ---

mcp = FastMCP("otto", lifespan=app_lifespan)


def _get_ctx(ctx: Context) -> AppContext:
    return ctx.request_context.lifespan_context


def _get_session(app_ctx: AppContext, session_id: str) -> BrowserSession:
    if not _SESSION_ID_RE.match(session_id):
        raise ValueError("Invalid session ID format: expected 12 hex characters.")
    session = app_ctx.sessions.get(session_id)
    if session is None:
        raise ValueError(f"No active session with id '{session_id}'. Use launch_session first.")
    if not session.is_active:
        raise ValueError(f"Session '{session_id}' is no longer active.")
    return session


def _load_env(app_ctx: AppContext) -> dict[str, str]:
    """Lazy-load .env variables on first use."""
    if app_ctx.env_vars is None:
        try:
            app_ctx.env_vars = load_env_vars()
        except EnvLoadError as e:
            raise ValueError(str(e)) from e
    return app_ctx.env_vars


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
               WARNING: Using a proxy triggers botasaurus-driver's proxy authentication
               subsystem, which imports javascript-fixes — a package that runs
               'npm install' at import time without a lockfile. Only use proxy in
               trusted environments where Node.js is installed.
        download_dir: Directory for downloaded files. Default: './downloads'.
    """
    app_ctx = _get_ctx(ctx)

    async with app_ctx._launch_lock:
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
        detail_level: 'summary' (default) returns compact overview with element counts.
                      'full' returns all interactive elements (large response).
    """
    app_ctx = _get_ctx(ctx)
    session = _get_session(app_ctx, session_id)

    await ctx.info("Scouting page...")
    report: ScoutReport = await asyncio.to_thread(
        scout_page, session.driver, focus_frame
    )

    # Cache elements for find_elements queries
    session.cache_elements(report.interactive_elements)

    # Record in history (always stores summary-level)
    session.history.record_scout(report)

    await ctx.info(f"Scout complete: {report.page_summary}")

    if detail_level == "full":
        return sanitize_response(report.model_dump(exclude_none=True))

    # Summary mode: return structure + counts, no element list
    element_summary = build_element_summary(report.interactive_elements)
    return sanitize_response({
        "page_metadata": report.page_metadata.model_dump(exclude_none=True),
        "iframe_map": [f.model_dump(exclude_none=True) for f in report.iframe_map],
        "shadow_dom_boundaries": [s.model_dump(exclude_none=True) for s in report.shadow_dom_boundaries],
        "element_summary": element_summary.model_dump(exclude_none=True),
        "page_summary": report.page_summary,
    })


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
    max_results = min(max(max_results, 1), MAX_RESULTS)
    app_ctx = _get_ctx(ctx)
    session = _get_session(app_ctx, session_id)

    # Use cached elements or re-scout if cache is empty
    elements = session.get_cached_elements()
    if elements is None:
        await ctx.info("No cached elements — scouting page first...")
        report: ScoutReport = await asyncio.to_thread(
            scout_page, session.driver, None
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

    return sanitize_response({
        "matched": len(matched),
        "total_on_page": len(elements),
        "elements": stripped,
    })


# --- Tool: execute_action ---


@mcp.tool()
async def execute_action_tool(
    session_id: str,
    action: Literal["click", "type", "select", "navigate", "scroll", "wait", "press_key", "hover", "clear"],
    selector: str | None = None,
    value: str | None = None,
    frame_context: str | None = None,
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
        wait_after: Milliseconds to wait after action completes. Default: 500.
    """
    wait_after = min(max(wait_after, 0), MAX_WAIT_MS)
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

    return sanitize_response(result.model_dump(exclude_none=True))


# --- Tool: fill_secret ---


@mcp.tool()
async def fill_secret(
    session_id: str,
    env_var: str,
    selector: str,
    frame_context: str | None = None,
    clear_first: bool = True,
    wait_after: int = 500,
    ctx: Context[ServerSession, AppContext] = None,
) -> dict:
    """Type a secret value from .env into a form field without exposing it in the conversation.

    The server reads the value from the .env file and types it directly into the
    target element. The actual value never appears in tool parameters or responses.

    Args:
        session_id: Active session ID.
        env_var: Name of the environment variable in .env (e.g., 'APP_PASSWORD').
        selector: CSS selector of the target input field.
        frame_context: Iframe selector path for the target element. Use 'main' or omit for top-level.
        clear_first: Clear the field before typing. Default: true.
        wait_after: Milliseconds to wait after typing. Default: 500.
    """
    wait_after = min(max(wait_after, 0), MAX_WAIT_MS)
    import time
    from datetime import datetime, timezone

    from .actions import _resolve_target

    app_ctx = _get_ctx(ctx)
    session = _get_session(app_ctx, session_id)

    start = time.perf_counter()
    timestamp = datetime.now(timezone.utc).isoformat()

    # Load the secret value server-side
    try:
        env = _load_env(app_ctx)
    except ValueError as e:
        return FillSecretResult(
            success=False, env_var=env_var, selector=selector,
            error=str(e),
        ).model_dump(exclude_none=True)

    if env_var not in env:
        return FillSecretResult(
            success=False, env_var=env_var, selector=selector,
            error=f"Environment variable '{env_var}' not found. Check your .env file.",
        ).model_dump(exclude_none=True)

    secret_value = env[env_var]

    # Get URL before action (driver access is sync — must use thread)
    try:
        url_before = await asyncio.to_thread(lambda: session.driver.current_url)
    except Exception:
        url_before = ""

    # Type the value into the field (synchronous driver operations)
    error = None
    try:
        target = await asyncio.to_thread(_resolve_target, session.driver, frame_context)
        if clear_first:
            await asyncio.to_thread(target.clear, selector)
        await asyncio.to_thread(target.type, selector, secret_value)
    except Exception as e:
        error = str(e)

    # Wait after action (non-blocking)
    if wait_after > 0:
        await asyncio.sleep(wait_after / 1000)

    # Get URL after action (driver access is sync — must use thread)
    try:
        url_after = await asyncio.to_thread(lambda: session.driver.current_url)
    except Exception:
        url_after = url_before

    elapsed = int((time.perf_counter() - start) * 1000)

    # Record in history with reference, NOT the actual value
    record = ActionRecord(
        action="type",
        selector=selector,
        value=f"${{{env_var}}}",
        frame_context=frame_context,
        success=error is None,
        url_before=url_before,
        url_after=url_after,
        timestamp=timestamp,
        error=error,
    )
    session.history.record_action(record)
    if url_before != url_after:
        session.history.record_navigation(url_after)
    session.invalidate_element_cache()

    result = FillSecretResult(
        success=error is None,
        env_var=env_var,
        selector=selector,
        chars_typed=len(secret_value) if error is None else 0,
        url_changed=url_before != url_after,
        current_url=url_after,
        error=error,
        elapsed_ms=elapsed,
    )

    if result.success:
        await ctx.info(f"Secret '{env_var}' typed into '{selector}' ({result.chars_typed} chars)")
    else:
        await ctx.warning(f"fill_secret failed: {error}")

    return result.model_dump(exclude_none=True)


# --- Tool: execute_javascript ---


@mcp.tool()
async def execute_javascript(
    session_id: str,
    script: str,
    frame_context: str | None = None,
    ctx: Context[ServerSession, AppContext] = None,
) -> dict:
    """Execute arbitrary JavaScript in the page context and return the result.

    Use this to debug click failures, read shadow DOM content, dispatch custom
    events, extract data, or perform any DOM operation not covered by other tools.

    Args:
        session_id: Active session ID.
        script: JavaScript code to execute. The last expression is returned as the result.
        frame_context: Iframe selector path for execution context. Use 'main' or omit for top-level.
    """
    app_ctx = _get_ctx(ctx)
    session = _get_session(app_ctx, session_id)

    await ctx.info("Executing JavaScript...")
    result, record = await asyncio.to_thread(
        run_javascript, session.driver, script, frame_context
    )

    session.history.record_javascript(record)

    # JS can modify the DOM arbitrarily, so invalidate cached elements
    session.invalidate_element_cache()

    if result.success:
        await ctx.info(f"JS executed: {result.result_type} result")
    else:
        await ctx.warning(f"JS execution failed: {result.error}")

    return sanitize_response(result.model_dump(exclude_none=True))


# --- Tool: take_screenshot ---


@mcp.tool()
async def take_screenshot_tool(
    session_id: str,
    format: Literal["png", "jpeg"] = "png",
    quality: int | None = None,
    clip_x: float | None = None,
    clip_y: float | None = None,
    clip_width: float | None = None,
    clip_height: float | None = None,
    full_page: bool = False,
    ctx: Context[ServerSession, AppContext] = None,
) -> CallToolResult:
    """Capture a screenshot of the current page. Returns the image inline so Claude can see it.

    Use this for visual verification after clicks, to see page state, or to debug
    layout issues. Supports optional clip region to zoom into specific areas.

    Args:
        session_id: Active session ID.
        format: Image format: 'png' or 'jpeg'. Default: 'png'.
        quality: JPEG quality (1-100). Only used when format='jpeg'.
        clip_x: Left coordinate of clip region (viewport pixels).
        clip_y: Top coordinate of clip region (viewport pixels).
        clip_width: Width of clip region.
        clip_height: Height of clip region.
        full_page: Capture the full scrollable page, not just viewport. Default: false.
                   Note: pages with lazy-loaded content may still show incomplete results.
    """
    app_ctx = _get_ctx(ctx)
    session = _get_session(app_ctx, session_id)

    await ctx.info("Taking screenshot...")
    result, record, raw_bytes = await asyncio.to_thread(
        take_screenshot,
        session.driver,
        image_format=format,
        quality=quality,
        clip_x=clip_x,
        clip_y=clip_y,
        clip_width=clip_width,
        clip_height=clip_height,
        full_page=full_page,
    )

    session.history.record_screenshot(record)

    if not result.success or raw_bytes is None:
        await ctx.warning(f"Screenshot failed: {result.error}")
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(result.model_dump(exclude_none=True)))],
            isError=True,
        )

    await ctx.info(f"Screenshot captured: {result.byte_size} bytes ({format})")

    # Return metadata as text + image inline for visual display
    mime = f"image/{format}"
    return CallToolResult(
        content=[
            TextContent(type="text", text=json.dumps(result.model_dump(exclude_none=True))),
            ImageContent(type="image", data=base64.b64encode(raw_bytes).decode(), mimeType=mime),
        ]
    )


# --- Tool: inspect_element ---


@mcp.tool()
async def inspect_element_tool(
    session_id: str,
    selector: str,
    frame_context: str | None = None,
    include_listeners: bool = False,
    include_children: bool = True,
    ctx: Context[ServerSession, AppContext] = None,
) -> dict:
    """Inspect a single DOM element in detail — visibility, position, shadow DOM, overlays, and more.

    Use this to diagnose why a click didn't work, check if an element is obscured by
    an overlay, verify shadow DOM context, or examine element state before interacting.

    Args:
        session_id: Active session ID.
        selector: CSS selector of the element to inspect.
        frame_context: Iframe selector path. Use 'main' or omit for top-level.
        include_listeners: Detect inline event handlers (onclick, etc.). Default: false.
        include_children: Include child element summary. Default: true.
    """
    app_ctx = _get_ctx(ctx)
    session = _get_session(app_ctx, session_id)

    await ctx.info(f"Inspecting element: {selector}")
    inspection = await asyncio.to_thread(
        inspect_element,
        session.driver,
        selector,
        frame_context,
        include_listeners,
        include_children,
    )

    if inspection.found:
        status = "visible" if inspection.is_visible else "hidden"
        if inspection.is_obscured:
            status += f", obscured by {inspection.obscured_by}"
        await ctx.info(f"Element found: <{inspection.tag}> ({status})")
    else:
        await ctx.warning(f"Element not found: {selector}")

    return sanitize_response(inspection.model_dump(exclude_none=True))


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
    timeout_ms = min(max(timeout_ms, 0), MAX_TIMEOUT_MS)
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
            return sanitize_response(MonitorResult(
                events=events,
                total_captured=len(monitor.events),
                monitoring_active=monitor.monitoring,
            ).model_dump(exclude_none=True))

        case "wait_for_download":
            await ctx.info(f"Waiting for download (timeout: {timeout_ms}ms)...")
            download_events = await asyncio.to_thread(monitor.wait_for_download, timeout_ms)
            return sanitize_response(MonitorResult(
                events=download_events,
                total_captured=len(monitor.events),
                monitoring_active=monitor.monitoring,
            ).model_dump(exclude_none=True))

        case _:
            return {"error": f"Unknown command: {command}"}


# --- Tool: record_video ---


@mcp.tool()
async def record_video(
    session_id: str,
    command: Literal["start", "stop", "status"],
    max_width: int = 1280,
    max_height: int = 720,
    quality: int = 80,
    target_fps: int = 10,
    ctx: Context[ServerSession, AppContext] = None,
) -> dict:
    """Control video recording for the current browser session.

    Records the browser screen using CDP screencast and encodes to MP4.
    Requires ffmpeg for video encoding: install imageio-ffmpeg (pip install 'imageio-ffmpeg')
    or have ffmpeg on your system PATH. Without it, raw JPEG frames are saved instead.

    Args:
        session_id: Active session ID.
        command: start: begin recording. stop: stop and encode video. status: check recording state.
        max_width: Maximum video width in pixels. Default: 1280.
        max_height: Maximum video height in pixels. Default: 720.
        quality: JPEG frame quality (1-100). Default: 80.
        target_fps: Target frames per second (approximate). Default: 10.
    """
    max_width = min(max(max_width, 320), 1920)
    max_height = min(max(max_height, 240), 1080)
    quality = min(max(quality, 1), 100)
    target_fps = min(max(target_fps, 1), 30)

    app_ctx = _get_ctx(ctx)
    session = _get_session(app_ctx, session_id)
    monitor = session.screencast_monitor

    match command:
        case "start":
            await ctx.info(f"Starting video recording ({max_width}x{max_height} @ {target_fps}fps)...")
            await asyncio.to_thread(
                monitor.start, session.driver, max_width, max_height, quality, target_fps
            )
            return RecordingResult(
                recording_active=True,
                started_at=monitor._started_at,
                target_fps=target_fps,
                resolution=f"{max_width}x{max_height}",
            ).model_dump(exclude_none=True)

        case "stop":
            await ctx.info("Stopping recording and encoding video...")
            result = await asyncio.to_thread(monitor.stop)

            # Record in session history
            from datetime import datetime, timezone
            record = RecordingRecord(
                started_at=monitor._started_at or "",
                stopped_at=monitor._stopped_at or "",
                duration_seconds=result["duration_seconds"],
                frame_count=result["frame_count"],
                video_path=result.get("video_path"),
                encoded=result["encoded"],
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            session.history.record_recording(record)

            recording_result = RecordingResult(
                recording_active=False,
                video_path=result.get("video_path"),
                frames_dir=result.get("frames_dir"),
                frame_count=result["frame_count"],
                duration_seconds=result["duration_seconds"],
                encoded=result["encoded"],
                encode_warning=result.get("encode_warning"),
            )

            if result["encoded"]:
                await ctx.info(
                    f"Video saved: {result['video_path']} "
                    f"({result['frame_count']} frames, {result['duration_seconds']}s)"
                )
            else:
                warning = result.get("encode_warning") or result.get("error") or "Encoding unavailable"
                await ctx.warning(warning)

            return recording_result.model_dump(exclude_none=True)

        case "status":
            status = monitor.status()
            return RecordingResult(
                recording_active=status["recording"],
                frame_count=status["frame_count"],
                started_at=status["started_at"],
                elapsed_seconds=status["elapsed_seconds"],
                target_fps=status["target_fps"],
                resolution=status["resolution"],
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
    captured, and the sequence of URLs visited. Use this data to compose botasaurus-driver scripts.

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
    return sanitize_response(history.model_dump(exclude_none=True))


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
