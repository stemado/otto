"""Action execution — click, type, navigate, and other browser interactions."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .models import ActionRecord, ActionResult

if TYPE_CHECKING:
    from botasaurus_driver import Driver


def execute_action(
    driver: Driver,
    action: str,
    selector: str | None = None,
    value: str | None = None,
    frame_context: str | None = None,
    shadow_pierce: bool = False,
    wait_after: int = 500,
) -> tuple[ActionResult, ActionRecord]:
    """Execute a single browser action and return the result + history record.

    Args:
        driver: Active botasaurus-driver instance.
        action: One of: click, type, select, navigate, scroll, wait, press_key, hover, clear.
        selector: CSS selector for the target element (required for most actions).
        value: Context-dependent value (text to type, URL to navigate, key to press, etc.).
        frame_context: Iframe selector path, or None/'main' for top-level page.
        shadow_pierce: Whether selector needs shadow DOM piercing.
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

    try:
        # Resolve frame context — get the target to operate on
        target = _resolve_target(driver, frame_context)

        match action:
            case "click":
                _require(selector, "selector required for click")
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

    result = ActionResult(
        success=error is None,
        action_performed=action_desc,
        url_changed=url_before != url_after,
        current_url=url_after,
        error=error,
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
