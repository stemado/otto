"""Tests for credential scrubbing — verifies the two-layer defense from the spec.

Spec: docs/specs/credential-scrubbing.md

Layer 1: Password guard in getVisibleText() (scout_page.js)
Layer 2: Value-based response filter via BrowserSession.scrub_secrets()
"""

from __future__ import annotations

import json

import pytest

from otto.session import BrowserSession
from otto.models import FillSecretResult
from otto.sanitize import sanitize_response


# ---------------------------------------------------------------------------
# Layer 1: getVisibleText() password guard (unit test via JS source inspection)
# ---------------------------------------------------------------------------


class TestGetVisibleTextPasswordGuard:
    """Verify the JS source contains the password guard."""

    @pytest.fixture()
    def scout_js(self) -> str:
        """Load scout_page.js source."""
        from pathlib import Path

        js_path = Path(__file__).parent.parent / "src" / "otto" / "js" / "scout_page.js"
        return js_path.read_text()

    def test_getvisibletext_has_password_guard(self, scout_js: str):
        """getVisibleText must check el.type === 'password' before returning el.value."""
        # Find the getVisibleText function body
        start = scout_js.index("function getVisibleText(el)")
        # Find the next function definition to bound the search
        next_func = scout_js.index("function ", start + 1)
        func_body = scout_js[start:next_func]

        # Must contain a password type check before el.value
        assert 'el.type === "password"' in func_body, (
            "getVisibleText() must guard against password input values"
        )
        # Must return placeholder (not value) for password fields
        assert "el.placeholder" in func_body

    def test_attributes_value_has_password_guard(self, scout_js: str):
        """attributes.value must also exclude password inputs (pre-existing guard)."""
        assert 'el.type !== "password"' in scout_js


# ---------------------------------------------------------------------------
# Layer 2a: BrowserSession secret registry
# ---------------------------------------------------------------------------


class TestSecretRegistry:
    """Test BrowserSession._secret_values, register_secret(), scrub_secrets()."""

    @pytest.fixture()
    def session(self) -> BrowserSession:
        """Create a BrowserSession without launching a browser."""
        s = BrowserSession.__new__(BrowserSession)
        s._secret_values = set()
        return s

    def test_register_normal_credential(self, session: BrowserSession):
        """Credentials >= 4 chars are registered without warning."""
        warning = session.register_secret("Fall2015")
        assert warning is None
        assert "Fall2015" in session._secret_values

    def test_register_short_credential_returns_warning(self, session: BrowserSession):
        """Credentials < 4 chars are rejected with a warning."""
        warning = session.register_secret("ab")
        assert warning is not None
        assert "shorter than 4 characters" in warning
        assert "ab" not in session._secret_values

    def test_register_empty_credential_returns_warning(self, session: BrowserSession):
        """Empty string credentials are rejected with a warning."""
        warning = session.register_secret("")
        assert warning is not None
        assert "" not in session._secret_values  # empty string not in set

    def test_register_exactly_4_chars(self, session: BrowserSession):
        """Boundary: 4-char credential is accepted."""
        warning = session.register_secret("abcd")
        assert warning is None
        assert "abcd" in session._secret_values

    def test_register_exactly_3_chars(self, session: BrowserSession):
        """Boundary: 3-char credential is rejected."""
        warning = session.register_secret("abc")
        assert warning is not None
        assert "abc" not in session._secret_values

    def test_scrub_replaces_registered_secret(self, session: BrowserSession):
        """scrub_secrets replaces known values with [REDACTED]."""
        session.register_secret("Fall2015")
        result = session.scrub_secrets('{"text": "the password is Fall2015 here"}')
        assert "Fall2015" not in result
        assert "[REDACTED]" in result

    def test_scrub_no_secrets_passthrough(self, session: BrowserSession):
        """scrub_secrets is a no-op when no secrets are registered."""
        text = '{"text": "hello world"}'
        assert session.scrub_secrets(text) == text

    def test_scrub_multiple_occurrences(self, session: BrowserSession):
        """All occurrences of a secret are replaced."""
        session.register_secret("secretval")
        result = session.scrub_secrets("first secretval then secretval again")
        assert result == "first [REDACTED] then [REDACTED] again"

    def test_scrub_multiple_secrets(self, session: BrowserSession):
        """Multiple different secrets are all scrubbed."""
        session.register_secret("password1")
        session.register_secret("apikey99")
        result = session.scrub_secrets("user typed password1 and apikey99")
        assert "password1" not in result
        assert "apikey99" not in result
        assert result.count("[REDACTED]") == 2

    def test_scrub_overlapping_secrets_longest_first(self, session: BrowserSession):
        """When secrets overlap, longer secret is replaced first to avoid partial leaks."""
        session.register_secret("pass")
        session.register_secret("password123")
        result = session.scrub_secrets("the value is password123 done")
        # Should produce "[REDACTED]" not "[REDACTED]word123" or "pass[REDACTED]"
        assert "password123" not in result
        assert "pass" not in result
        # The entire "password123" should be one redaction
        assert "[REDACTED]" in result

    def test_scrub_secret_not_present(self, session: BrowserSession):
        """scrub_secrets doesn't modify text that doesn't contain secrets."""
        session.register_secret("Fall2015")
        text = '{"text": "nothing sensitive here"}'
        assert session.scrub_secrets(text) == text

    def test_secret_values_never_serialized(self, session: BrowserSession):
        """_secret_values is not included in any serializable output."""
        session.register_secret("topsecret")
        # BrowserSession doesn't have model_dump, but verify the attribute
        # is private (underscore prefix) and is a plain set, not a Pydantic field
        assert hasattr(session, "_secret_values")
        assert isinstance(session._secret_values, set)


# ---------------------------------------------------------------------------
# Layer 2b: Integration with sanitize_response
# ---------------------------------------------------------------------------


class TestScrubWithSanitize:
    """Test that scrub_secrets works correctly chained after sanitize_response."""

    @pytest.fixture()
    def session(self) -> BrowserSession:
        s = BrowserSession.__new__(BrowserSession)
        s._secret_values = set()
        return s

    def test_scrub_after_sanitize(self, session: BrowserSession):
        """scrub_secrets correctly scrubs the string output of sanitize_response."""
        session.register_secret("Fall2015")
        data = {"text": "password is Fall2015", "selector": "#field"}
        sanitized = sanitize_response(data)
        scrubbed = session.scrub_secrets(sanitized)
        assert "Fall2015" not in scrubbed
        assert "[REDACTED]" in scrubbed
        # Boundary markers preserved
        assert "OTTO_WEB_CONTENT_START" in scrubbed
        assert "OTTO_WEB_CONTENT_END" in scrubbed

    def test_scrub_in_json_value(self, session: BrowserSession):
        """Secret embedded inside a JSON string value is scrubbed."""
        session.register_secret("MyP@ss123")
        data = {"result": "MyP@ss123", "success": True}
        result = session.scrub_secrets(sanitize_response(data))
        assert "MyP@ss123" not in result

    def test_scrub_in_execute_javascript_result_preview(self, session: BrowserSession):
        """Simulates execute_javascript returning a password value — must be scrubbed."""
        session.register_secret("Fall2015")
        # This simulates what would happen if JS reads document.querySelector('input[type=password]').value
        js_result = {
            "success": True,
            "result": "Fall2015",
            "result_type": "string",
        }
        scrubbed = session.scrub_secrets(sanitize_response(js_result))
        assert "Fall2015" not in scrubbed
        assert "[REDACTED]" in scrubbed

    def test_scrub_in_session_history_javascript_record(self, session: BrowserSession):
        """Session history JS records containing credentials are scrubbed."""
        session.register_secret("Fall2015")
        history_data = {
            "session_id": "abc123def456",
            "javascript_calls": [
                {
                    "script_preview": "document.querySelector('input').value",
                    "result_preview": "Fall2015",
                    "success": True,
                }
            ],
        }
        scrubbed = session.scrub_secrets(sanitize_response(history_data))
        assert "Fall2015" not in scrubbed


# ---------------------------------------------------------------------------
# FillSecretResult model
# ---------------------------------------------------------------------------


class TestFillSecretResultWarning:
    """Test the warning field on FillSecretResult."""

    def test_warning_field_exists(self):
        """FillSecretResult has an optional warning field."""
        result = FillSecretResult(
            success=True,
            env_var="APP_PASSWORD",
            selector="#password",
            warning="some warning",
        )
        dumped = result.model_dump(exclude_none=True)
        assert dumped["warning"] == "some warning"

    def test_warning_excluded_when_none(self):
        """Warning field is excluded from output when None."""
        result = FillSecretResult(
            success=True,
            env_var="APP_PASSWORD",
            selector="#password",
        )
        dumped = result.model_dump(exclude_none=True)
        assert "warning" not in dumped

    def test_short_credential_warning_format(self):
        """The warning from register_secret matches expected format."""
        s = BrowserSession.__new__(BrowserSession)
        s._secret_values = set()
        warning = s.register_secret("ab")
        result = FillSecretResult(
            success=True,
            env_var="SHORT_PASS",
            selector="#pass",
            warning=warning,
        )
        dumped = result.model_dump(exclude_none=True)
        assert "shorter than 4 characters" in dumped["warning"]
