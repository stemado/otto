"""Unit tests for Issue #1 bugfixes — iframe click guard, scroll aliases, network pagination.

These are pure-Python unit tests that do NOT require a real browser.
Run: uv run pytest tests/test_bugfixes.py -v
"""

from unittest.mock import MagicMock

import pytest

from otto.actions import _parse_scroll_value, _selector_targets_iframe, execute_action
from otto.models import NetworkEvent
from otto.network import NetworkMonitor


# ---------------------------------------------------------------------------
# Fix 1: _selector_targets_iframe
# ---------------------------------------------------------------------------


class TestSelectorTargetsIframe:
    """Zero-cost regex check that detects iframe selectors."""

    def test_bare_iframe(self):
        assert _selector_targets_iframe("iframe") is True

    def test_iframe_with_attribute(self):
        assert _selector_targets_iframe('iframe[src*="membership.io"]') is True

    def test_iframe_with_id(self):
        assert _selector_targets_iframe("iframe#content") is True

    def test_iframe_with_class(self):
        assert _selector_targets_iframe("iframe.main-frame") is True

    def test_iframe_nested_child(self):
        assert _selector_targets_iframe("div > iframe") is True

    def test_iframe_descendant(self):
        assert _selector_targets_iframe(".wrapper iframe[src='foo']") is True

    def test_iframe_sibling(self):
        assert _selector_targets_iframe("div + iframe") is True

    def test_iframe_general_sibling(self):
        assert _selector_targets_iframe("div ~ iframe") is True

    def test_iframe_case_insensitive(self):
        assert _selector_targets_iframe("IFRAME#content") is True
        assert _selector_targets_iframe("IFrame[src='x']") is True

    def test_iframe_with_pseudo(self):
        assert _selector_targets_iframe("iframe:first-child") is True

    def test_not_iframe_button(self):
        assert _selector_targets_iframe("#click-btn") is False

    def test_not_iframe_wrapper(self):
        """Custom element 'iframe-wrapper' is NOT an iframe tag."""
        assert _selector_targets_iframe("iframe-wrapper") is False

    def test_not_iframe_class_only(self):
        assert _selector_targets_iframe(".iframe-class") is False

    def test_not_iframe_data_attr(self):
        assert _selector_targets_iframe("[data-iframe='true']") is False

    def test_not_iframe_id(self):
        assert _selector_targets_iframe("#iframe") is False

    def test_click_iframe_returns_error(self):
        """execute_action returns an error when clicking an iframe selector."""
        mock_driver = MagicMock()
        mock_driver.current_url = "http://example.com"
        result, record = execute_action(
            mock_driver,
            "click",
            selector='iframe[src*="membership.io"]',
            wait_after=0,
        )
        assert result.success is False
        assert "frame_context" in result.error
        assert "Cannot click" in result.error


# ---------------------------------------------------------------------------
# Fix 2: _parse_scroll_value
# ---------------------------------------------------------------------------


class TestParseScrollValue:
    """Scroll value parser supporting aliases and pixel amounts."""

    def test_down(self):
        assert _parse_scroll_value("down") == 500

    def test_up(self):
        assert _parse_scroll_value("up") == -500

    def test_down_case_insensitive(self):
        assert _parse_scroll_value("Down") == 500
        assert _parse_scroll_value("DOWN") == 500

    def test_up_case_insensitive(self):
        assert _parse_scroll_value("Up") == -500

    def test_numeric_positive(self):
        assert _parse_scroll_value("300") == 300

    def test_numeric_negative(self):
        assert _parse_scroll_value("-200") == -200

    def test_none_default(self):
        assert _parse_scroll_value(None) == 500

    def test_empty_default(self):
        assert _parse_scroll_value("") == 500

    def test_whitespace_stripped(self):
        assert _parse_scroll_value("  down  ") == 500

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid scroll value"):
            _parse_scroll_value("sideways")


class TestScrollAction:
    """execute_action scroll with string aliases and frame context."""

    def _mock_driver(self):
        driver = MagicMock()
        driver.current_url = "http://example.com"
        return driver

    def test_scroll_down_string(self):
        driver = self._mock_driver()
        result, _ = execute_action(driver, "scroll", value="down", wait_after=0)
        assert result.success is True
        driver.run_js.assert_called_once()
        call_arg = driver.run_js.call_args[0][0]
        assert "scrollBy" in call_arg
        assert "500" in call_arg

    def test_scroll_up_string(self):
        driver = self._mock_driver()
        result, _ = execute_action(driver, "scroll", value="up", wait_after=0)
        assert result.success is True
        call_arg = driver.run_js.call_args[0][0]
        assert "scrollBy" in call_arg
        assert "-500" in call_arg

    def test_scroll_top(self):
        driver = self._mock_driver()
        result, _ = execute_action(driver, "scroll", value="top", wait_after=0)
        assert result.success is True
        call_arg = driver.run_js.call_args[0][0]
        assert "scrollTo(0, 0)" in call_arg
        assert "top" in result.action_performed.lower()

    def test_scroll_bottom(self):
        driver = self._mock_driver()
        result, _ = execute_action(driver, "scroll", value="bottom", wait_after=0)
        assert result.success is True
        call_arg = driver.run_js.call_args[0][0]
        assert "scrollTo" in call_arg
        assert "scrollHeight" in call_arg
        assert "bottom" in result.action_performed.lower()

    def test_scroll_uses_target_not_driver(self):
        """Scroll with frame_context uses target.run_js, not driver.run_js."""
        driver = self._mock_driver()
        mock_iframe = MagicMock()
        driver.select_iframe.return_value = mock_iframe

        result, _ = execute_action(
            driver, "scroll", value="300",
            frame_context="iframe#content", wait_after=0,
        )
        assert result.success is True
        mock_iframe.run_js.assert_called_once()
        driver.run_js.assert_not_called()


# ---------------------------------------------------------------------------
# Fix 3: Network query pagination
# ---------------------------------------------------------------------------


def _make_event(url: str, status: int = 200) -> NetworkEvent:
    return NetworkEvent(
        url=url, method="GET", status=status,
        timestamp="2026-02-21T00:00:00Z",
    )


class TestNetworkQueryPagination:
    """NetworkMonitor.query() pagination and output capping."""

    def test_default_limit_caps_at_100(self):
        monitor = NetworkMonitor("./downloads")
        monitor.events = [_make_event(f"http://example.com/{i}") for i in range(200)]
        result = monitor.query()
        assert len(result) == 100

    def test_limit_zero_returns_all(self):
        monitor = NetworkMonitor("./downloads")
        monitor.events = [_make_event(f"http://example.com/{i}") for i in range(200)]
        result = monitor.query(limit=0)
        assert len(result) == 200

    def test_custom_limit(self):
        monitor = NetworkMonitor("./downloads")
        monitor.events = [_make_event(f"http://example.com/{i}") for i in range(50)]
        result = monitor.query(limit=10)
        assert len(result) == 10

    def test_offset(self):
        monitor = NetworkMonitor("./downloads")
        monitor.events = [_make_event(f"http://example.com/{i}") for i in range(10)]
        result = monitor.query(limit=0, offset=5)
        assert len(result) == 5
        assert result[0].url == "http://example.com/5"

    def test_limit_and_offset_combined(self):
        monitor = NetworkMonitor("./downloads")
        monitor.events = [_make_event(f"http://example.com/{i}") for i in range(20)]
        result = monitor.query(limit=3, offset=5)
        assert len(result) == 3
        assert result[0].url == "http://example.com/5"
        assert result[2].url == "http://example.com/7"

    def test_url_pattern_with_limit(self):
        monitor = NetworkMonitor("./downloads")
        monitor.events = [
            _make_event("http://example.com/api/data"),
            _make_event("http://example.com/other"),
            _make_event("http://example.com/api/data2"),
            _make_event("http://example.com/api/data3"),
        ]
        result = monitor.query(url_pattern="api/data", limit=2)
        assert len(result) == 2
        assert all("api/data" in e.url for e in result)

    def test_query_all_bypasses_limit(self):
        monitor = NetworkMonitor("./downloads")
        monitor.events = [_make_event(f"http://example.com/{i}") for i in range(200)]
        result = monitor.query_all()
        assert len(result) == 200

    def test_query_all_with_pattern(self):
        monitor = NetworkMonitor("./downloads")
        monitor.events = [
            _make_event("http://example.com/api/data"),
            _make_event("http://example.com/other"),
        ]
        result = monitor.query_all("api/data")
        assert len(result) == 1

    def test_total_count_property(self):
        monitor = NetworkMonitor("./downloads")
        monitor.events = [_make_event(f"http://example.com/{i}") for i in range(150)]
        assert monitor.total_count == 150

    def test_total_count_unaffected_by_query(self):
        """total_count reflects the full list, not the paginated result."""
        monitor = NetworkMonitor("./downloads")
        monitor.events = [_make_event(f"http://example.com/{i}") for i in range(200)]
        _ = monitor.query(limit=10)
        assert monitor.total_count == 200

    def test_pending_body_captures_indices_stable(self):
        """Verify event list indices remain stable (no FIFO eviction)."""
        monitor = NetworkMonitor("./downloads")
        for i in range(5):
            monitor.events.append(_make_event(f"http://example.com/{i}"))
        monitor._pending_body_captures = [(2, "req2"), (4, "req4")]
        assert monitor.events[2].url == "http://example.com/2"
        assert monitor.events[4].url == "http://example.com/4"

    def test_small_event_list_under_limit(self):
        """When events < limit, return all without error."""
        monitor = NetworkMonitor("./downloads")
        monitor.events = [_make_event(f"http://example.com/{i}") for i in range(5)]
        result = monitor.query()
        assert len(result) == 5

    def test_empty_events_query(self):
        monitor = NetworkMonitor("./downloads")
        result = monitor.query()
        assert result == []
