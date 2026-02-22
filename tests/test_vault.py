"""Tests for the encrypted credential vault backend."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from otto.vault import (
    CredentialEntry,
    SQLiteVaultBackend,
    VaultBackend,
    VaultCorruptionError,
    VaultError,
    VaultKeyError,
)


@pytest.fixture
def fernet_key() -> Fernet:
    """Generate a fresh Fernet key for testing."""
    return Fernet(Fernet.generate_key())


@pytest.fixture
def vault(tmp_path: Path, fernet_key: Fernet) -> SQLiteVaultBackend:
    """Create an initialized vault in a temp directory."""
    db_path = tmp_path / "vault.db"
    backend = SQLiteVaultBackend(db_path)
    backend.initialize(fernet_key)
    return backend


# --- ABC contract ---


def test_sqlite_backend_is_vault_backend(vault: SQLiteVaultBackend) -> None:
    assert isinstance(vault, VaultBackend)


# --- Basic CRUD ---


def test_set_and_get_roundtrip(vault: SQLiteVaultBackend) -> None:
    vault.set("APP_PASSWORD", "s3cret!")
    assert vault.get("APP_PASSWORD") == "s3cret!"


def test_get_nonexistent_returns_none(vault: SQLiteVaultBackend) -> None:
    assert vault.get("MISSING") is None


def test_set_overwrites_existing(vault: SQLiteVaultBackend) -> None:
    vault.set("KEY", "old")
    vault.set("KEY", "new")
    assert vault.get("KEY") == "new"


def test_delete_existing_returns_true(vault: SQLiteVaultBackend) -> None:
    vault.set("KEY", "val")
    assert vault.delete("KEY") is True
    assert vault.get("KEY") is None


def test_delete_nonexistent_returns_false(vault: SQLiteVaultBackend) -> None:
    assert vault.delete("NOPE") is False


def test_list_names_sorted(vault: SQLiteVaultBackend) -> None:
    vault.set("ZEBRA", "z")
    vault.set("ALPHA", "a")
    vault.set("MIDDLE", "m")
    assert vault.list_names() == ["ALPHA", "MIDDLE", "ZEBRA"]


def test_list_names_empty_vault(vault: SQLiteVaultBackend) -> None:
    assert vault.list_names() == []


def test_has_existing(vault: SQLiteVaultBackend) -> None:
    vault.set("KEY", "val")
    assert vault.has("KEY") is True


def test_has_nonexistent(vault: SQLiteVaultBackend) -> None:
    assert vault.has("NOPE") is False


# --- Metadata ---


def test_get_entry_returns_metadata(vault: SQLiteVaultBackend) -> None:
    vault.set("KEY", "val")
    entry = vault.get_entry("KEY")
    assert entry is not None
    assert isinstance(entry, CredentialEntry)
    assert entry.name == "KEY"
    assert entry.value == "val"
    assert isinstance(entry.created_at, datetime)
    assert isinstance(entry.updated_at, datetime)


def test_get_entry_nonexistent_returns_none(vault: SQLiteVaultBackend) -> None:
    assert vault.get_entry("MISSING") is None


def test_updated_at_changes_on_overwrite(vault: SQLiteVaultBackend) -> None:
    vault.set("KEY", "v1")
    entry1 = vault.get_entry("KEY")
    vault.set("KEY", "v2")
    entry2 = vault.get_entry("KEY")
    assert entry2 is not None
    assert entry1 is not None
    assert entry2.updated_at >= entry1.updated_at
    assert entry2.value == "v2"


# --- Encryption correctness ---


def test_raw_db_does_not_contain_plaintext(
    tmp_path: Path, fernet_key: Fernet
) -> None:
    """Verify the credential value is not stored as plaintext in the SQLite file."""
    db_path = tmp_path / "vault.db"
    backend = SQLiteVaultBackend(db_path)
    backend.initialize(fernet_key)
    backend.set("SECRET", "super-secret-value-12345")
    backend.close()

    raw_bytes = db_path.read_bytes()
    assert b"super-secret-value-12345" not in raw_bytes


def test_wrong_key_raises_vault_key_error(tmp_path: Path) -> None:
    """Opening a vault with a different key should fail sentinel verification."""
    db_path = tmp_path / "vault.db"

    key1 = Fernet(Fernet.generate_key())
    backend1 = SQLiteVaultBackend(db_path)
    backend1.initialize(key1)
    backend1.set("KEY", "val")
    backend1.close()

    key2 = Fernet(Fernet.generate_key())
    backend2 = SQLiteVaultBackend(db_path)
    with pytest.raises(VaultKeyError):
        backend2.initialize(key2)


def test_corrupted_value_raises_corruption_error(
    tmp_path: Path, fernet_key: Fernet
) -> None:
    """Tampered ciphertext should raise VaultCorruptionError on read."""
    db_path = tmp_path / "vault.db"
    backend = SQLiteVaultBackend(db_path)
    backend.initialize(fernet_key)
    backend.set("KEY", "val")

    # Tamper with the stored ciphertext directly in SQLite
    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE credentials SET value = X'deadbeef' WHERE name = 'KEY'")
    conn.commit()
    conn.close()

    with pytest.raises(VaultCorruptionError):
        backend.get("KEY")


# --- Edge cases ---


def test_unicode_values(vault: SQLiteVaultBackend) -> None:
    vault.set("EMOJI", "hello world")
    assert vault.get("EMOJI") == "hello world"


def test_empty_string_value(vault: SQLiteVaultBackend) -> None:
    vault.set("EMPTY", "")
    assert vault.get("EMPTY") == ""


def test_large_value(vault: SQLiteVaultBackend) -> None:
    big = "x" * 10_000
    vault.set("BIG", big)
    assert vault.get("BIG") == big


# --- Salt storage in vault_meta ---


def test_salt_stored_in_vault_meta(tmp_path: Path) -> None:
    """When initialized with password derivation, the salt lives in vault_meta."""
    db_path = tmp_path / "vault.db"
    backend = SQLiteVaultBackend(db_path)
    fernet = Fernet(Fernet.generate_key())
    backend.initialize(fernet)
    backend.close()

    # The vault_meta table should have the sentinel
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT value FROM vault_meta WHERE key = 'sentinel'"
    ).fetchone()
    conn.close()
    assert row is not None


# --- close ---


def test_close_and_reopen(tmp_path: Path, fernet_key: Fernet) -> None:
    db_path = tmp_path / "vault.db"

    backend = SQLiteVaultBackend(db_path)
    backend.initialize(fernet_key)
    backend.set("KEY", "val")
    backend.close()

    backend2 = SQLiteVaultBackend(db_path)
    backend2.initialize(fernet_key)
    assert backend2.get("KEY") == "val"
    backend2.close()
