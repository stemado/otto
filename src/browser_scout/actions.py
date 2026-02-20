"""Action execution — click, type, navigate, and other browser interactions."""

from __future__ import annotations

import base64
import json
import os
import re
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from .models import (
    ActionRecord,
    ActionResult,
    ElementInspection,
    JavaScriptRecord,
    JavaScriptResult,
    ScreenshotRecord,
    ScreenshotResult,
)

if TYPE_CHECKING:
    from botasaurus_driver import Driver

# Load inspect element JS once at module level
_JS_DIR = os.path.join(os.path.dirname(__file__), "js")
_INSPECT_JS: str | None = None


def _get_inspect_js() -> str:
    global _INSPECT_JS
    if _INSPECT_JS is None:
        with open(os.path.join(_JS_DIR, "inspect_element.js"), encoding="utf-8") as f:
            _INSPECT_JS = f.read()
    return _INSPECT_JS


def execute_action(
    driver: Driver,
    action: str,
    selector: str | None = None,
    value: str | None = None,
    frame_context: str | None = None,
    wait_after: int = 500,
) -> tuple[ActionResult, ActionRecord]:
    """Execute a single browser action and return the result + history record.

    Args:
        driver: Active botasaurus-driver instance.
        action: One of: click, type, select, navigate, scroll, wait, press_key, hover, clear.
        selector: CSS selector for the target element (required for most actions).
        value: Context-dependent value (text to type, URL to navigate, key to press, etc.).
        frame_context: Iframe selector path, or None/'main' for top-level page.
        wait_after: Milliseconds to wait after action completes.

    Returns:
        Tuple of (ActionResult for the tool response, ActionRecord for history).
    """
    start = time.perf_counter()
    timestamp = datetime.now(timezone.utc).isoformat()

    try:
        url_before = driver.current_url
    except Exception:
        url_before = ""

    error = None
    action_desc = ""
    pre_click_fingerprint = None

    try:
        # Resolve frame context — get the target to operate on
        target = _resolve_target(driver, frame_context)

        match action:
            case "click":
                _require(selector, "selector required for click")
                # Capture DOM fingerprint before click for verification
                pre_click_fingerprint = _capture_dom_fingerprint(driver)
                target.click(selector)
                action_desc = f"Clicked '{selector}'"

            case "type":
                _require(selector, "selector required for type")
                _require(value, "value required for type")
                target.type(selector, value)
                action_desc = f"Typed into '{selector}'"

            case "select":
                _require(selector, "selector required for select")
                _require(value, "value required for select")
                # botasaurus-driver's select_option supports value, index, or label
                if value.isdigit():
                    target.select_option(selector, index=int(value))
                else:
                    target.select_option(selector, value=value)
                action_desc = f"Selected '{value}' in '{selector}'"

            case "navigate":
                _require(value, "value (URL) required for navigate")
                driver.get(value)
                action_desc = f"Navigated to '{value}'"

            case "scroll":
                amount = int(value) if value else 500
                driver.run_js(f"window.scrollBy(0, {amount})")
                action_desc = f"Scrolled by {amount}px"

            case "wait":
                # value is always milliseconds for consistency with wait_after
                if selector:
                    wait_sec = int(value or 8000) / 1000
                    target.wait_for_element(selector, wait=wait_sec)
                    action_desc = f"Waited for element '{selector}' (timeout: {wait_sec}s)"
                elif value:
                    time.sleep(int(value) / 1000)
                    action_desc = f"Waited {value}ms"
                else:
                    time.sleep(1)
                    action_desc = "Waited 1000ms"

            case "press_key":
                _require(value, "value (key name) required for press_key")
                # Use CDP Input.dispatchKeyEvent for reliable key presses
                from botasaurus_driver import cdp
                key_map = _get_key_map()
                key_info = key_map.get(value.lower(), {"key": value, "code": f"Key{value.upper()}"})

                driver.run_cdp_command(cdp.input_.dispatch_key_event(
                    type_="keyDown",
                    key=key_info["key"],
                    code=key_info["code"],
                    windows_virtual_key_code=key_info.get("keyCode", 0),
                ))
                driver.run_cdp_command(cdp.input_.dispatch_key_event(
                    type_="keyUp",
                    key=key_info["key"],
                    code=key_info["code"],
                    windows_virtual_key_code=key_info.get("keyCode", 0),
                ))
                action_desc = f"Pressed key '{value}'"

            case "hover":
                _require(selector, "selector required for hover")
                # Get element position and dispatch mouse move (json.dumps for safe JS escaping)
                sel_js = json.dumps(selector)
                hover_js = (
                    "const el = document.querySelector(" + sel_js + ");"
                    "if (!el) return null;"
                    "const rect = el.getBoundingClientRect();"
                    "return {x: rect.x + rect.width/2, y: rect.y + rect.height/2};"
                )
                pos = driver.run_js(hover_js)
                if pos:
                    from botasaurus_driver import cdp
                    driver.run_cdp_command(cdp.input_.dispatch_mouse_event(
                        type_="mouseMoved",
                        x=pos["x"],
                        y=pos["y"],
                    ))
                    action_desc = f"Hovered over '{selector}'"
                else:
                    raise ValueError(f"Element not found for hover: {selector}")

            case "clear":
                _require(selector, "selector required for clear")
                target.clear(selector)
                action_desc = f"Cleared '{selector}'"

            case _:
                raise ValueError(f"Unknown action: {action}")

    except Exception as e:
        error = str(e)
        action_desc = action_desc or f"Failed: {action}"

    # Wait after action
    if wait_after > 0:
        time.sleep(wait_after / 1000)

    try:
        url_after = driver.current_url
    except Exception:
        url_after = url_before

    elapsed = int((time.perf_counter() - start) * 1000)

    # Post-click verification: detect clicks that had no visible effect
    warning = None
    if (
        error is None
        and action == "click"
        and pre_click_fingerprint is not None
        and url_before == url_after
    ):
        post_fingerprint = _capture_dom_fingerprint(driver)
        if post_fingerprint and post_fingerprint == pre_click_fingerprint:
            warning = (
                "Click reported success but no DOM changes detected (URL, child count, "
                "title, and aria-hidden count are all unchanged). The click may not have "
                "had an effect. Consider using inspect_element to check if the element is "
                "visible, obscured, or in a shadow DOM. Increasing wait_after may help if "
                "the page uses async rendering."
            )

    result = ActionResult(
        success=error is None,
        action_performed=action_desc,
        url_changed=url_before != url_after,
        current_url=url_after,
        error=error,
        warning=warning,
        elapsed_ms=elapsed,
    )

    record = ActionRecord(
        action=action,
        selector=selector,
        value=value,
        frame_context=frame_context,
        success=error is None,
        url_before=url_before,
        url_after=url_after,
        timestamp=timestamp,
        error=error,
    )

    return result, record


def _resolve_target(driver: Driver, frame_context: str | None):
    """Resolve the execution target (driver or iframe handle)."""
    if not frame_context or frame_context == "main":
        return driver

    # frame_context is a CSS selector for the iframe
    # Try select_iframe first (handles both same-origin and cross-origin)
    iframe = driver.select_iframe(frame_context)
    if iframe is None:
        raise ValueError(f"Iframe not found: {frame_context}")
    return iframe


def _require(val, message: str) -> None:
    if not val:
        raise ValueError(message)


def _capture_dom_fingerprint(driver: Driver) -> dict | None:
    """Capture a lightweight DOM fingerprint for change detection."""
    try:
        return driver.run_js(
            "return {"
            "  childCount: document.body ? document.body.children.length : 0,"
            "  title: document.title,"
            "  ariaHiddenCount: document.querySelectorAll('[aria-hidden]').length"
            "}"
        )
    except Exception:
        return None


def run_javascript(
    driver: Driver,
    script: str,
    frame_context: str | None = None,
) -> tuple[JavaScriptResult, JavaScriptRecord]:
    """Execute arbitrary JavaScript in the page context.

    Args:
        driver: Active botasaurus-driver instance.
        script: JavaScript code to execute. The last expression is returned.
        frame_context: Iframe selector path, or None/'main' for top-level page.

    Returns:
        Tuple of (JavaScriptResult for tool response, JavaScriptRecord for history).
    """
    start = time.perf_counter()
    timestamp = datetime.now(timezone.utc).isoformat()

    try:
        target = _resolve_target(driver, frame_context)
        raw_result = target.run_js(script)

        # Classify the result type and normalize
        if raw_result is None:
            result_type = "undefined"
            result_value = None
        elif isinstance(raw_result, bool):
            result_type = "boolean"
            result_value = raw_result
        elif isinstance(raw_result, (int, float)):
            result_type = "number"
            result_value = raw_result
        elif isinstance(raw_result, str):
            result_type = "string"
            result_value = raw_result
        elif isinstance(raw_result, list):
            result_type = "array"
            result_value = raw_result
        elif isinstance(raw_result, dict):
            result_type = "object"
            result_value = raw_result
        else:
            # Non-serializable — coerce to string
            result_type = "string"
            result_value = str(raw_result)

        elapsed = int((time.perf_counter() - start) * 1000)

        js_result = JavaScriptResult(
            success=True,
            result=result_value,
            result_type=result_type,
            elapsed_ms=elapsed,
        )

        # Build compact preview for history
        result_str = json.dumps(result_value, default=str) if result_value is not None else "undefined"
        record = JavaScriptRecord(
            script_preview=script[:200],
            frame_context=frame_context,
            success=True,
            result_preview=result_str[:500],
            timestamp=timestamp,
        )

        return js_result, record

    except Exception as e:
        elapsed = int((time.perf_counter() - start) * 1000)

        js_result = JavaScriptResult(
            success=False,
            error=str(e),
            elapsed_ms=elapsed,
        )

        record = JavaScriptRecord(
            script_preview=script[:200],
            frame_context=frame_context,
            success=False,
            result_preview=f"ERROR: {e}"[:500],
            timestamp=timestamp,
        )

        return js_result, record


def take_screenshot(
    driver: Driver,
    image_format: str = "png",
    quality: int | None = None,
    clip_x: float | None = None,
    clip_y: float | None = None,
    clip_width: float | None = None,
    clip_height: float | None = None,
    full_page: bool = False,
) -> tuple[ScreenshotResult, ScreenshotRecord, bytes | None]:
    """Capture a screenshot of the current page via CDP.

    Args:
        driver: Active botasaurus-driver instance.
        image_format: Image format: 'png' or 'jpeg'.
        quality: JPEG quality (1-100). Only used when image_format='jpeg'.
        clip_x, clip_y, clip_width, clip_height: Optional clip region.
        full_page: If True, capture the full scrollable page. Note: pages with
                   lazy-loaded content may still show incomplete results.

    Returns:
        Tuple of (ScreenshotResult metadata, ScreenshotRecord for history, raw image bytes or None on error).
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    clipped = all(v is not None for v in (clip_x, clip_y, clip_width, clip_height))

    if image_format not in ("png", "jpeg"):
        return (
            ScreenshotResult(success=False, format=image_format, error=f"Invalid format '{image_format}'. Must be 'png' or 'jpeg'."),
            ScreenshotRecord(format=image_format, timestamp=timestamp),
            None,
        )

    try:
        from botasaurus_driver import cdp

        # Build CDP screenshot parameters
        kwargs: dict[str, Any] = {"format_": image_format}

        if image_format == "jpeg" and quality is not None:
            kwargs["quality"] = quality

        if clipped:
            kwargs["clip"] = cdp.page.Viewport(
                x=clip_x,
                y=clip_y,
                width=clip_width,
                height=clip_height,
                scale=1,
            )

        if full_page:
            kwargs["capture_beyond_viewport"] = True

        # CDP returns base64-encoded image data
        b64_data = driver.run_cdp_command(cdp.page.capture_screenshot(**kwargs))
        raw_bytes = base64.b64decode(b64_data)

        result = ScreenshotResult(
            success=True,
            format=image_format,
            byte_size=len(raw_bytes),
            clipped=clipped,
        )

        record = ScreenshotRecord(
            format=image_format,
            clipped=clipped,
            full_page=full_page,
            timestamp=timestamp,
        )

        return result, record, raw_bytes

    except Exception as e:
        result = ScreenshotResult(
            success=False,
            format=image_format,
            error=str(e),
        )

        record = ScreenshotRecord(
            format=image_format,
            clipped=clipped,
            full_page=full_page,
            timestamp=timestamp,
        )

        return result, record, None


def inspect_element(
    driver: Driver,
    selector: str,
    frame_context: str | None = None,
    include_listeners: bool = False,
    include_children: bool = True,
) -> ElementInspection:
    """Inspect a single DOM element in detail.

    Args:
        driver: Active botasaurus-driver instance.
        selector: CSS selector of the element to inspect.
        frame_context: Iframe selector path, or None/'main' for top-level page.
        include_listeners: Whether to attempt detecting event listeners. Default: false.
        include_children: Whether to include children summary. Default: true.

    Returns:
        ElementInspection with detailed element analysis.
    """
    try:
        target = _resolve_target(driver, frame_context)

        js_template = _get_inspect_js()
        # Single-pass replacement to prevent cascading substitution
        # (avoids corruption if selector contains placeholder text)
        replacements = {
            "__SELECTOR__": json.dumps(selector),
            "__INCLUDE_LISTENERS__": json.dumps(include_listeners),
            "__INCLUDE_CHILDREN__": json.dumps(include_children),
        }
        pattern = re.compile("|".join(re.escape(k) for k in replacements))
        js_code = pattern.sub(lambda m: replacements[m.group(0)], js_template)

        raw = target.run_js(js_code)

        if isinstance(raw, str):
            data = json.loads(raw)
        elif isinstance(raw, dict):
            data = raw
        else:
            return ElementInspection(
                found=False,
                selector=selector,
                error=f"Unexpected result type from inspect JS: {type(raw)}",
            )

        return ElementInspection(
            found=data.get("found", False),
            selector=selector,
            tag=data.get("tag", ""),
            bounding_rect=data.get("bounding_rect", {}),
            computed_visibility=data.get("computed_visibility", {}),
            is_visible=data.get("is_visible", False),
            is_obscured=data.get("is_obscured", False),
            obscured_by=data.get("obscured_by"),
            in_shadow_dom=data.get("in_shadow_dom", False),
            shadow_host=data.get("shadow_host"),
            parent_chain=data.get("parent_chain", []),
            attributes=data.get("attributes", {}),
            aria=data.get("aria", {}),
            input_state=data.get("input_state", {}),
            children_summary=data.get("children_summary", {}),
            event_listeners=data.get("event_listeners", []),
        )

    except Exception as e:
        return ElementInspection(
            found=False,
            selector=selector,
            error=str(e),
        )


def _get_key_map() -> dict:
    """Map common key names to CDP key event parameters."""
    return {
        "enter": {"key": "Enter", "code": "Enter", "keyCode": 13},
        "tab": {"key": "Tab", "code": "Tab", "keyCode": 9},
        "escape": {"key": "Escape", "code": "Escape", "keyCode": 27},
        "space": {"key": " ", "code": "Space", "keyCode": 32},
        "backspace": {"key": "Backspace", "code": "Backspace", "keyCode": 8},
        "delete": {"key": "Delete", "code": "Delete", "keyCode": 46},
        "arrowup": {"key": "ArrowUp", "code": "ArrowUp", "keyCode": 38},
        "arrowdown": {"key": "ArrowDown", "code": "ArrowDown", "keyCode": 40},
        "arrowleft": {"key": "ArrowLeft", "code": "ArrowLeft", "keyCode": 37},
        "arrowright": {"key": "ArrowRight", "code": "ArrowRight", "keyCode": 39},
        "home": {"key": "Home", "code": "Home", "keyCode": 36},
        "end": {"key": "End", "code": "End", "keyCode": 35},
        "pageup": {"key": "PageUp", "code": "PageUp", "keyCode": 33},
        "pagedown": {"key": "PageDown", "code": "PageDown", "keyCode": 34},
    }
