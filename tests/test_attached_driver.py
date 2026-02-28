"""Guard tests for AttachedDriver.

These tests verify that the botasaurus-driver internals we depend on
still expose the interfaces AttachedBrowser/AttachedDriver override.
If a botasaurus-driver upgrade breaks any of these, the test name tells
you exactly which assumption failed.
"""

from botasaurus_driver.core.browser import Browser
from botasaurus_driver.core.config import Config


def test_browser_has_start_method():
    """AttachedBrowser overrides start() — it must exist and be callable."""
    assert hasattr(Browser, "start")
    assert callable(getattr(Browser, "start"))


def test_browser_close_calls_discrete_connection_methods():
    """AttachedBrowser.close() calls these individually instead of
    Browser.close() which also kills the process."""
    assert hasattr(Browser, "close_tab_connections")
    assert callable(getattr(Browser, "close_tab_connections"))

    assert hasattr(Browser, "close_browser_connection")
    assert callable(getattr(Browser, "close_browser_connection"))


def test_config_accepts_host_and_port():
    """AttachedDriver passes host/port to Config to target an existing
    Chrome debug endpoint."""
    config = Config(host="127.0.0.1", port=9222)
    assert config.host == "127.0.0.1"
    assert config.port == 9222


def test_browser_has_websocket_url_property():
    """We read websocket_url to confirm connectivity."""
    assert hasattr(Browser, "websocket_url")
    assert isinstance(getattr(Browser, "websocket_url"), property)


def test_browser_has_update_targets():
    """AttachedBrowser.start() calls update_targets() for tab discovery."""
    assert hasattr(Browser, "update_targets")
    assert callable(getattr(Browser, "update_targets"))


def test_browser_has_handle_target_update():
    """AttachedBrowser.start() registers _handle_target_update as CDP handler."""
    assert hasattr(Browser, "_handle_target_update")


def test_attached_browser_inherits_browser():
    """AttachedBrowser must be a Browser subclass for Driver compatibility."""
    from otto.attached_driver import AttachedBrowser

    assert issubclass(AttachedBrowser, Browser)


def test_attached_driver_inherits_driver():
    """AttachedDriver must be a Driver subclass."""
    from botasaurus_driver import Driver

    from otto.attached_driver import AttachedDriver

    assert issubclass(AttachedDriver, Driver)
