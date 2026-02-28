"""Attached browser/driver — connect to an existing Chrome instance via CDP.

Used by the Hot Takeover feature to attach to a browser owned by otto-engine.
The key difference from a normal Driver: we never launch or kill the Chrome
process.  We only open/close CDP connections.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from botasaurus_driver import Driver
from botasaurus_driver.core.browser import Browser, Connection
from botasaurus_driver.core.config import Config
from botasaurus_driver.core import util
from botasaurus_driver import cdp


class AttachedBrowser(Browser):
    """A Browser that attaches to an already-running Chrome process.

    Overrides ``start()`` instead of just ``create_chrome_with_retries``
    because the parent's ``start()`` assumes a subprocess exists after
    creation (accesses ``self._process.pid``).  We skip process management
    entirely and wire up only the CDP connection and target discovery.
    """

    def start(self) -> "Browser":
        """Connect to an existing Chrome and set up CDP.

        Replaces the parent ``start()`` to avoid:
        - launching a subprocess (we poll ``/json/version`` instead)
        - accessing ``self._process.pid`` (no process to own)
        - cleaning up profile directories (engine owns the profile)
        """
        self.config.host = self.config.host or "127.0.0.1"

        # Poll the existing Chrome's debug endpoint.
        chrome_url = f"http://{self.config.host}:{self.config.port}/json/version"
        self.info = _poll_chrome(chrome_url, timeout=10)
        self._process = None
        self._process_pid = None

        # Wire up the CDP browser-level connection.
        self.connection = Connection(self.info["webSocketDebuggerUrl"], _owner=self)

        self.connection.handlers[cdp.target.TargetInfoChanged] = [
            self._handle_target_update
        ]
        self.connection.handlers[cdp.target.TargetCreated] = [
            self._handle_target_update
        ]
        self.connection.handlers[cdp.target.TargetDestroyed] = [
            self._handle_target_update
        ]
        self.connection.handlers[cdp.target.TargetCrashed] = [
            self._handle_target_update
        ]

        # Register so botasaurus can track us (we deregister in close).
        instances = util.get_registered_instances()
        instances.add(self)

        # Discover existing targets (tabs) in the running Chrome.
        self.connection.send(
            cdp.target.set_discover_targets(discover=True),
            wait_for_response=False,
        )
        self.update_targets()
        return self

    def close(self):
        """Close CDP connections only — never kill Chrome."""
        self.close_tab_connections()
        self.close_browser_connection()

        # Deregister from the global instance set so botasaurus's
        # atexit handler doesn't try to clean us up.
        instances = util.get_registered_instances()
        try:
            instances.remove(self)
        except KeyError:
            pass


class AttachedDriver(Driver):
    """A Driver that connects to an existing Chrome via CDP.

    Usage::

        driver = AttachedDriver(host="127.0.0.1", port=51234)
        driver.current_url   # whatever page the engine left it on
        # ... scout, interact, inspect ...
        driver.close()       # drops CDP — Chrome stays alive
    """

    def __init__(self, host: str, port: int) -> None:
        # Build a Config pointing at the existing Chrome.
        self.config = Config(headless=False, host=host, port=port)

        self._tab_value = None
        self._browser: Browser = _start_attached(self.config)
        self._dot_name = None
        self._cursor = None
        self._is_human_mode_enabled = False

        # BrowserTab.__init__ wires up the tab/connection plumbing.
        super(Driver, self).__init__(
            self.config, self._tab_value, None, self, self._browser
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _poll_chrome(url: str, timeout: float = 10) -> dict:
    """Poll ``/json/version`` until Chrome responds or *timeout* expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, OSError):
            time.sleep(0.2)
    raise ConnectionError(
        f"Could not reach Chrome at {url} within {timeout}s. "
        "Is the otto-engine execution still running?"
    )


def _start_attached(config: Config) -> AttachedBrowser:
    """Create an AttachedBrowser and connect it to the running Chrome."""
    browser = AttachedBrowser(config)
    browser.start()  # calls our overridden start()
    return browser
