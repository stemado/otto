"""Integration tests for network.py — CDP network monitoring lifecycle.

Requires a real browser (botasaurus-driver), so skip in CI.
Run manually: uv run pytest tests/test_network.py -v -s
"""

import time

import pytest

from browser_scout.actions import execute_action
from browser_scout.session import BrowserSession

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def session(base_url):
    """Launch a real browser session for network monitoring tests."""
    s = BrowserSession(headless=True)
    s.launch(base_url + "/network.html")
    yield s
    s.close()


@pytest.fixture(autouse=True)
def reset_monitor(session, base_url):
    """Reset network monitor and page state before each test."""
    session.network_monitor.stop()
    session.network_monitor.clear()
    session.driver.get(base_url + "/network.html")


def _click_and_wait(driver, selector, delay=1.0):
    """Click a button and wait for the network request to complete."""
    execute_action(driver, "click", selector, wait_after=0)
    time.sleep(delay)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_start_enables_monitoring(session):
    """Starting the monitor sets the monitoring flag."""
    monitor = session.network_monitor
    monitor.start(session.driver)
    assert monitor.monitoring is True


def test_stop_disables_monitoring(session):
    """Stopping the monitor clears the monitoring flag."""
    monitor = session.network_monitor
    monitor.start(session.driver)
    monitor.stop()
    assert monitor.monitoring is False


def test_events_empty_before_activity(session):
    """No events captured before any network activity."""
    monitor = session.network_monitor
    monitor.start(session.driver)
    events = monitor.query()
    assert events == []


# ---------------------------------------------------------------------------
# Request-response capture
# ---------------------------------------------------------------------------


def test_captures_fetch_request(session):
    """Monitor captures a fetch() request triggered by button click."""
    monitor = session.network_monitor
    monitor.start(session.driver)

    _click_and_wait(session.driver, "#fetch-json")

    events = monitor.query()
    api_events = [e for e in events if "/api/data" in e.url]
    assert len(api_events) >= 1

    event = api_events[0]
    assert event.status == 200
    assert event.response_type == "json"
    assert event.method == "GET"


def test_captures_navigation(session, base_url):
    """Monitor captures navigation requests."""
    monitor = session.network_monitor
    monitor.start(session.driver)

    execute_action(session.driver, "navigate", value=base_url + "/navigate.html", wait_after=0)
    time.sleep(1)

    events = monitor.query()
    nav_events = [e for e in events if "navigate.html" in e.url]
    assert len(nav_events) >= 1
    assert nav_events[0].response_type == "html"


def test_stopped_monitor_ignores_events(session):
    """Events after stop() are not captured."""
    monitor = session.network_monitor
    monitor.start(session.driver)
    monitor.stop()

    _click_and_wait(session.driver, "#fetch-json")

    events = monitor.query()
    api_events = [e for e in events if "/api/data" in e.url]
    assert len(api_events) == 0


# ---------------------------------------------------------------------------
# URL pattern filtering
# ---------------------------------------------------------------------------


def test_start_pattern_filters(session):
    """URL pattern at start() time filters captured events."""
    monitor = session.network_monitor
    monitor.start(session.driver, url_pattern="api/data")

    _click_and_wait(session.driver, "#fetch-json")
    _click_and_wait(session.driver, "#fetch-other")

    events = monitor.query()
    # Only /api/data should be captured, not /api/other
    assert all("/api/data" in e.url for e in events if "/api/" in e.url)
    assert not any("/api/other" in e.url for e in events)


def test_query_pattern_filters(session):
    """URL pattern at query() time filters returned events."""
    monitor = session.network_monitor
    monitor.start(session.driver)

    _click_and_wait(session.driver, "#fetch-json")
    _click_and_wait(session.driver, "#fetch-other")

    # Query with a filter should only return matching events
    filtered = monitor.query(url_pattern="api/data")
    assert len(filtered) >= 1
    assert all("/api/data" in e.url for e in filtered)


# ---------------------------------------------------------------------------
# Download detection
# ---------------------------------------------------------------------------


def test_download_detected(session):
    """Download response with Content-Disposition is detected."""
    monitor = session.network_monitor
    monitor.start(session.driver)

    _click_and_wait(session.driver, "#fetch-download")

    events = monitor.query()
    download_events = [e for e in events if e.triggered_download]
    assert len(download_events) >= 1
    assert download_events[0].download_filename == "report.csv"


def test_wait_for_download_timeout(session):
    """wait_for_download returns empty list on timeout when no download occurs."""
    monitor = session.network_monitor
    monitor.start(session.driver)

    # No download triggered — should timeout
    result = monitor.wait_for_download(timeout_ms=500)
    assert result == []


# ---------------------------------------------------------------------------
# Body capture
# ---------------------------------------------------------------------------


def test_body_capture_enabled(session):
    """With capture_bodies=True, response bodies are available after query."""
    monitor = session.network_monitor
    monitor.start(session.driver, capture_bodies=True)

    _click_and_wait(session.driver, "#fetch-json")

    events = monitor.query()
    api_events = [e for e in events if "/api/data" in e.url]
    assert len(api_events) >= 1

    body = api_events[0].response_body
    assert body is not None
    assert "key" in body


def test_body_not_captured_by_default(session):
    """Without capture_bodies, response bodies are None."""
    monitor = session.network_monitor
    monitor.start(session.driver)

    _click_and_wait(session.driver, "#fetch-json")

    events = monitor.query()
    api_events = [e for e in events if "/api/data" in e.url]
    assert len(api_events) >= 1
    assert api_events[0].response_body is None


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------


def test_clear_empties_state(session):
    """clear() removes all captured events."""
    monitor = session.network_monitor
    monitor.start(session.driver)

    _click_and_wait(session.driver, "#fetch-json")
    assert len(monitor.query()) > 0

    monitor.clear()
    assert len(monitor.events) == 0
