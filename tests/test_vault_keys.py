"""Tests for vault key resolution (keyring + master password fallback)."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from otto.vault import VaultKeyError
from otto.vault_keys import KEYRING_SERVICE, KEYRING_USERNAME, KeySource, PBKDF2_ITERATIONS


# --- Password derivation ---


def test_password_derives_consistent_key(tmp_path: Path) -> None:
    """Same password + same salt = same key."""
    db_path = tmp_path / "vault.db"
    _create_vault_db(db_path)

    f1 = KeySource._derive_from_password("mypass", db_path)
    f2 = KeySource._derive_from_password("mypass", db_path)
    # Fernet keys should be identical
    assert f1._signing_key == f2._signing_key
    assert f1._encryption_key == f2._encryption_key


def test_different_passwords_produce_different_keys(tmp_path: Path) -> None:
    db_path = tmp_path / "vault.db"
    _create_vault_db(db_path)

    f1 = KeySource._derive_from_password("password1", db_path)
    f2 = KeySource._derive_from_password("password2", db_path)
    assert f1._signing_key != f2._signing_key


def test_salt_created_in_vault_meta_on_first_derivation(tmp_path: Path) -> None:
    """First call should generate and store a salt in vault_meta."""
    db_path = tmp_path / "vault.db"
    _create_vault_db(db_path)

    KeySource._derive_from_password("pass", db_path)

    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT value FROM vault_meta WHERE key = 'pbkdf2_salt'"
    ).fetchone()
    conn.close()
    assert row is not None
    # Salt should be 16 bytes, stored as hex
    salt_bytes = bytes.fromhex(row[0])
    assert len(salt_bytes) == 16


def test_salt_reused_on_subsequent_derivation(tmp_path: Path) -> None:
    """Second call should read the existing salt, not generate a new one."""
    db_path = tmp_path / "vault.db"
    _create_vault_db(db_path)

    KeySource._derive_from_password("pass", db_path)

    # Read the stored salt
    conn = sqlite3.connect(str(db_path))
    salt1 = conn.execute(
        "SELECT value FROM vault_meta WHERE key = 'pbkdf2_salt'"
    ).fetchone()[0]
    conn.close()

    # Derive again
    KeySource._derive_from_password("pass", db_path)

    conn = sqlite3.connect(str(db_path))
    salt2 = conn.execute(
        "SELECT value FROM vault_meta WHERE key = 'pbkdf2_salt'"
    ).fetchone()[0]
    conn.close()

    assert salt1 == salt2


# --- resolve() chain ---


def test_explicit_password_used(tmp_path: Path) -> None:
    """Explicit master_password arg should be used directly."""
    db_path = tmp_path / "vault.db"
    _create_vault_db(db_path)

    fernet = KeySource.resolve(db_path, master_password="explicit-pass")
    assert isinstance(fernet, Fernet)


def test_env_var_password(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """OTTO_VAULT_PASSWORD env var should be used when set."""
    db_path = tmp_path / "vault.db"
    _create_vault_db(db_path)

    monkeypatch.setenv("OTTO_VAULT_PASSWORD", "env-password")
    fernet = KeySource.resolve(db_path)
    assert isinstance(fernet, Fernet)


def test_explicit_password_overrides_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit password should win over env var."""
    db_path = tmp_path / "vault.db"
    _create_vault_db(db_path)

    monkeypatch.setenv("OTTO_VAULT_PASSWORD", "env-pass")
    f_explicit = KeySource.resolve(db_path, master_password="explicit-pass")
    f_env = KeySource._derive_from_password("env-pass", db_path)

    # They should produce different keys (different passwords, same salt)
    assert f_explicit._signing_key != f_env._signing_key


def test_keyring_used_when_available(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When keyring has a stored key, it should be used."""
    db_path = tmp_path / "vault.db"
    _create_vault_db(db_path)

    monkeypatch.delenv("OTTO_VAULT_PASSWORD", raising=False)

    stored_key = Fernet.generate_key().decode()
    mock_keyring = MagicMock()
    mock_keyring.get_password.return_value = stored_key

    with patch.dict("sys.modules", {"keyring": mock_keyring}):
        fernet = KeySource.resolve(db_path)

    assert isinstance(fernet, Fernet)
    mock_keyring.get_password.assert_called_once_with(KEYRING_SERVICE, KEYRING_USERNAME)


def test_keyring_generates_new_key_when_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When keyring is available but empty, a new key should be generated and stored."""
    db_path = tmp_path / "vault.db"
    _create_vault_db(db_path)

    monkeypatch.delenv("OTTO_VAULT_PASSWORD", raising=False)

    mock_keyring = MagicMock()
    mock_keyring.get_password.return_value = None

    with patch.dict("sys.modules", {"keyring": mock_keyring}):
        fernet = KeySource.resolve(db_path)

    assert isinstance(fernet, Fernet)
    mock_keyring.set_password.assert_called_once()
    call_args = mock_keyring.set_password.call_args
    assert call_args[0][0] == KEYRING_SERVICE
    assert call_args[0][1] == KEYRING_USERNAME


def test_keyring_not_installed_falls_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When keyring is not installed, should fall through to next option."""
    db_path = tmp_path / "vault.db"
    _create_vault_db(db_path)

    monkeypatch.delenv("OTTO_VAULT_PASSWORD", raising=False)

    # Simulate keyring not installed by making import fail
    with patch.dict("sys.modules", {"keyring": None}):
        # Non-interactive, no keyring → should raise
        with pytest.raises(VaultKeyError, match="No encryption key available"):
            KeySource.resolve(db_path, interactive=False)


def test_keyring_backend_error_falls_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When keyring is installed but no backend, should fall through."""
    db_path = tmp_path / "vault.db"
    _create_vault_db(db_path)

    monkeypatch.delenv("OTTO_VAULT_PASSWORD", raising=False)

    mock_keyring = MagicMock()
    mock_keyring.get_password.side_effect = Exception("No keyring backend")

    with patch.dict("sys.modules", {"keyring": mock_keyring}):
        with pytest.raises(VaultKeyError, match="No encryption key available"):
            KeySource.resolve(db_path, interactive=False)


def test_keyring_import_error_logs_debug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """When keyring is not installed, a debug message should be logged."""
    db_path = tmp_path / "vault.db"
    _create_vault_db(db_path)

    monkeypatch.delenv("OTTO_VAULT_PASSWORD", raising=False)

    import logging

    with caplog.at_level(logging.DEBUG, logger="otto.vault_keys"):
        with patch.dict("sys.modules", {"keyring": None}):
            with pytest.raises(VaultKeyError):
                KeySource.resolve(db_path, interactive=False)

    assert any("keyring not installed" in r.message for r in caplog.records)


def test_keyring_backend_error_logs_debug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """When keyring backend fails, a debug message with the error should be logged."""
    db_path = tmp_path / "vault.db"
    _create_vault_db(db_path)

    monkeypatch.delenv("OTTO_VAULT_PASSWORD", raising=False)

    mock_keyring = MagicMock()
    mock_keyring.get_password.side_effect = RuntimeError("No suitable keyring backend")

    import logging

    with caplog.at_level(logging.DEBUG, logger="otto.vault_keys"):
        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            with pytest.raises(VaultKeyError):
                KeySource.resolve(db_path, interactive=False)

    assert any("keyring backend error" in r.message for r in caplog.records)
    assert any("No suitable keyring backend" in r.message for r in caplog.records)


# --- Non-interactive mode ---


def test_resolve_noninteractive_never_prompts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-interactive mode should never call getpass."""
    db_path = tmp_path / "vault.db"
    _create_vault_db(db_path)

    monkeypatch.delenv("OTTO_VAULT_PASSWORD", raising=False)

    # No keyring, no env var, non-interactive → should raise, not prompt
    with patch.dict("sys.modules", {"keyring": None}):
        with patch("otto.vault_keys._getpass_mod") as mock_getpass:
            with pytest.raises(VaultKeyError):
                KeySource.resolve(db_path, interactive=False)
            mock_getpass.getpass.assert_not_called()


# --- Helper ---


def _create_vault_db(db_path: Path) -> None:
    """Create a minimal vault database with the vault_meta table."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vault_meta (
            key   TEXT PRIMARY KEY,
            value BLOB NOT NULL
        )
    """)
    conn.commit()
    conn.close()
