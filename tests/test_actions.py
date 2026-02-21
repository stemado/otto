"""Integration tests for actions.py — browser action execution, JS, screenshots, inspect.

Requires a real browser (botasaurus-driver), so skip in CI.
Run manually: uv run pytest tests/test_actions.py -v -s
"""

import pytest

from otto.actions import (
    execute_action,
    inspect_element,
    run_javascript,
    take_screenshot,
)
from otto.session import BrowserSession

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def session(base_url):
    """Launch a real browser session for action testing."""
    s = BrowserSession(headless=True)
    s.launch(base_url + "/actions.html")
    yield s
    s.close()


@pytest.fixture(autouse=True)
def reset_page(session, base_url):
    """Reset to actions.html before each test to prevent state leakage."""
    session.driver.get(base_url + "/actions.html")


# ---------------------------------------------------------------------------
# execute_action — click
# ---------------------------------------------------------------------------


def test_click_updates_dom(session):
    """Click a button and verify the DOM changed."""
    result, record = execute_action(session.driver, "click", "#click-btn", wait_after=0)
    assert result.success is True
    assert record.action == "click"

    # Verify the onclick handler fired
    js_result, _ = run_javascript(session.driver, "return document.getElementById('click-result').textContent")
    assert js_result.result == "clicked"


def test_click_missing_selector(session):
    """Click without a selector returns an error."""
    result, record = execute_action(session.driver, "click", selector=None, wait_after=0)
    assert result.success is False
    assert "selector required" in result.error.lower()


def test_click_nonexistent_element(session):
    """Click on a nonexistent element returns an error."""
    result, _ = execute_action(session.driver, "click", "#nope", wait_after=0)
    assert result.success is False
    assert result.error is not None


def test_click_dom_changing_has_no_warning(session):
    """Click that causes a real DOM change does not produce a warning."""
    result, _ = execute_action(session.driver, "click", "#click-btn", wait_after=0)
    assert result.success is True
    # The onclick handler modifies the DOM, so no "no effect" warning
    assert result.warning is None


# ---------------------------------------------------------------------------
# execute_action — type
# ---------------------------------------------------------------------------


def test_type_fills_input(session):
    """Type text into an input and verify the value."""
    result, _ = execute_action(session.driver, "type", "#text-input", "hello world", wait_after=0)
    assert result.success is True

    js_result, _ = run_javascript(session.driver, "return document.getElementById('text-input').value")
    assert js_result.result == "hello world"


# ---------------------------------------------------------------------------
# execute_action — select
# ---------------------------------------------------------------------------


def test_select_by_value(session):
    """Select a dropdown option by value string."""
    result, _ = execute_action(session.driver, "select", "#color-select", "green", wait_after=0)
    assert result.success is True

    js_result, _ = run_javascript(session.driver, "return document.getElementById('color-select').value")
    assert js_result.result == "green"


def test_select_by_index(session):
    """Select a dropdown option by numeric index (triggers the isdigit path)."""
    result, _ = execute_action(session.driver, "select", "#color-select", "2", wait_after=0)
    assert result.success is True

    js_result, _ = run_javascript(session.driver, "return document.getElementById('color-select').value")
    assert js_result.result == "blue"


# ---------------------------------------------------------------------------
# execute_action — navigate
# ---------------------------------------------------------------------------


def test_navigate_changes_url(session, base_url):
    """Navigate to a different page and verify URL changed."""
    result, _ = execute_action(session.driver, "navigate", value=base_url + "/navigate.html", wait_after=0)
    assert result.success is True
    assert result.url_changed is True
    assert "navigate.html" in result.current_url


# ---------------------------------------------------------------------------
# execute_action — scroll
# ---------------------------------------------------------------------------


def test_scroll_moves_viewport(session):
    """Scroll default amount and verify viewport position changed."""
    # Reset scroll position
    run_javascript(session.driver, "window.scrollTo(0, 0)")

    result, _ = execute_action(session.driver, "scroll", wait_after=0)
    assert result.success is True

    js_result, _ = run_javascript(session.driver, "return window.scrollY")
    assert js_result.result > 0


# ---------------------------------------------------------------------------
# execute_action — wait
# ---------------------------------------------------------------------------


def test_wait_timed(session):
    """Timed wait completes successfully."""
    result, _ = execute_action(session.driver, "wait", value="100", wait_after=0)
    assert result.success is True
    assert result.elapsed_ms >= 100


def test_wait_for_element(session):
    """Wait for a dynamically injected element (appears after 1s)."""
    result, _ = execute_action(session.driver, "wait", selector="#delayed-element", value="5000", wait_after=0)
    assert result.success is True


# ---------------------------------------------------------------------------
# execute_action — press_key
# ---------------------------------------------------------------------------


def test_press_key_dispatches_event(session):
    """Press Enter key and verify the keydown event fired."""
    # Use JS to focus the input — botasaurus click doesn't trigger native focus
    run_javascript(session.driver, "document.getElementById('key-input').focus()")
    result, _ = execute_action(session.driver, "press_key", value="Enter", wait_after=0)
    assert result.success is True

    js_result, _ = run_javascript(session.driver, "return document.getElementById('key-result').textContent")
    assert js_result.result == "Enter"


# ---------------------------------------------------------------------------
# execute_action — hover
# ---------------------------------------------------------------------------


def test_hover_triggers_event(session):
    """Hover over an element and verify the mouseover event fired."""
    result, _ = execute_action(session.driver, "hover", "#hover-target", wait_after=0)
    assert result.success is True

    js_result, _ = run_javascript(
        session.driver,
        "return document.getElementById('hover-target').dataset.hovered",
    )
    assert js_result.result == "true"


# ---------------------------------------------------------------------------
# execute_action — clear
# ---------------------------------------------------------------------------


def test_clear_empties_input(session):
    """Type then clear an input field."""
    execute_action(session.driver, "type", "#text-input", "temporary", wait_after=0)
    result, _ = execute_action(session.driver, "clear", "#text-input", wait_after=0)
    assert result.success is True

    js_result, _ = run_javascript(session.driver, "return document.getElementById('text-input').value")
    assert js_result.result == ""


# ---------------------------------------------------------------------------
# execute_action — error / edge cases
# ---------------------------------------------------------------------------


def test_unknown_action(session):
    """Unknown action name returns an error."""
    result, _ = execute_action(session.driver, "destroy", wait_after=0)
    assert result.success is False
    assert "Unknown action" in result.error


def test_action_returns_record(session):
    """Verify ActionRecord fields are properly populated."""
    _, record = execute_action(session.driver, "click", "#click-btn", wait_after=0)
    assert record.action == "click"
    assert record.selector == "#click-btn"
    assert record.success is True
    assert record.url_before != ""
    assert record.url_after != ""
    assert record.timestamp != ""


def test_wait_after_adds_delay(session):
    """wait_after parameter adds measurable delay to elapsed time."""
    result_fast, _ = execute_action(session.driver, "click", "#click-btn", wait_after=0)
    result_slow, _ = execute_action(session.driver, "click", "#click-btn", wait_after=300)
    # The slow action should take at least 200ms more (allowing some tolerance)
    assert result_slow.elapsed_ms > result_fast.elapsed_ms + 200


# ---------------------------------------------------------------------------
# run_javascript
# ---------------------------------------------------------------------------


def test_js_returns_string(session):
    """JavaScript returning a string is classified correctly."""
    result, _ = run_javascript(session.driver, "return document.title")
    assert result.success is True
    assert result.result_type == "string"
    assert result.result == "Actions Test Page"


def test_js_returns_number(session):
    """JavaScript returning a number is classified correctly."""
    result, _ = run_javascript(session.driver, "return 42")
    assert result.success is True
    assert result.result_type == "number"
    assert result.result == 42


def test_js_returns_object(session):
    """JavaScript returning an object is classified correctly."""
    result, _ = run_javascript(session.driver, "return {a: 1, b: 'two'}")
    assert result.success is True
    assert result.result_type == "object"
    assert result.result["a"] == 1


def test_js_error(session):
    """JavaScript that throws returns an error."""
    result, _ = run_javascript(session.driver, "throw new Error('boom')")
    assert result.success is False
    assert result.error is not None


def test_js_record_preview(session):
    """Long scripts are truncated in the history record."""
    long_script = "return " + "'x' + " * 100 + "'x'"
    _, record = run_javascript(session.driver, long_script)
    assert len(record.script_preview) <= 200


# ---------------------------------------------------------------------------
# take_screenshot
# ---------------------------------------------------------------------------


def test_screenshot_png(session):
    """Default PNG screenshot succeeds with valid PNG bytes."""
    result, record, raw_bytes = take_screenshot(session.driver)
    assert result.success is True
    assert result.format == "png"
    assert result.byte_size > 0
    assert raw_bytes[:4] == b"\x89PNG"


def test_screenshot_jpeg(session):
    """JPEG screenshot succeeds with valid JPEG bytes."""
    result, _, raw_bytes = take_screenshot(session.driver, image_format="jpeg", quality=80)
    assert result.success is True
    assert result.format == "jpeg"
    assert raw_bytes[:2] == b"\xff\xd8"


def test_screenshot_invalid_format(session):
    """Invalid format returns an error without touching the browser."""
    result, _, raw_bytes = take_screenshot(session.driver, image_format="gif")
    assert result.success is False
    assert "Invalid format" in result.error
    assert raw_bytes is None


# ---------------------------------------------------------------------------
# inspect_element
# ---------------------------------------------------------------------------


def test_inspect_visible_button(session):
    """Inspect a visible button returns correct metadata."""
    inspection = inspect_element(session.driver, "#click-btn")
    assert inspection.found is True
    assert inspection.tag == "button"
    assert inspection.is_visible is True
    assert inspection.bounding_rect.get("width", 0) > 0


def test_inspect_hidden_element(session):
    """Inspect a display:none element reports it as not visible."""
    inspection = inspect_element(session.driver, "#hidden-el")
    assert inspection.found is True
    assert inspection.is_visible is False


def test_inspect_nonexistent(session):
    """Inspect a nonexistent element returns found=False."""
    inspection = inspect_element(session.driver, "#nope")
    assert inspection.found is False
