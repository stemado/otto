"""Encrypted credential vault with pluggable backend support.

Provides a ``VaultBackend`` abstract interface and a concrete
``SQLiteVaultBackend`` that stores credentials encrypted with Fernet
(AES-128-CBC + HMAC-SHA256) in a local SQLite database.

The ``cryptography`` package is imported lazily so that the module can
be loaded (for type checks / isinstance) even when the optional
``vault`` extras are not installed.
"""

from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cryptography.fernet import Fernet

# ---------------------------------------------------------------------------
# Default vault location
# ---------------------------------------------------------------------------

DEFAULT_VAULT_PATH = Path.home() / ".otto" / "vault.db"

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class VaultError(Exception):
    """Base exception for vault operations."""


class VaultKeyError(VaultError):
    """Raised when the encryption key cannot be obtained or is wrong."""


class VaultCorruptionError(VaultError):
    """Raised when stored data cannot be decrypted (wrong key or tampering)."""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class CredentialEntry:
    """A credential retrieved from the vault."""

    name: str
    value: str
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Abstract backend
# ---------------------------------------------------------------------------


class VaultBackend(ABC):
    """Abstract interface for credential storage backends."""

    @abstractmethod
    def get(self, name: str) -> str | None:
        """Retrieve a credential value by name.  Returns ``None`` if missing."""

    @abstractmethod
    def set(self, name: str, value: str) -> None:
        """Store or update a credential."""

    @abstractmethod
    def delete(self, name: str) -> bool:
        """Delete a credential.  Returns ``True`` if it existed."""

    @abstractmethod
    def list_names(self) -> list[str]:
        """Return all credential names (not values), sorted."""

    @abstractmethod
    def has(self, name: str) -> bool:
        """Check if a credential exists without retrieving its value."""

    @abstractmethod
    def get_entry(self, name: str) -> CredentialEntry | None:
        """Retrieve full credential metadata.  Returns ``None`` if missing."""

    @abstractmethod
    def close(self) -> None:
        """Release backend resources."""


# ---------------------------------------------------------------------------
# SQLite backend
# ---------------------------------------------------------------------------

_SENTINEL_PLAINTEXT = b"otto-vault-sentinel"


class SQLiteVaultBackend(VaultBackend):
    """Encrypted credential storage backed by a local SQLite database.

    Each credential *value* is individually encrypted with Fernet before
    being written.  The database itself is a normal (unencrypted) SQLite
    file — only the ``credentials.value`` column contains ciphertext.

    A sentinel value in ``vault_meta`` is used on open to verify that the
    correct encryption key was supplied.
    """

    def __init__(self, db_path: Path | str = DEFAULT_VAULT_PATH) -> None:
        self._db_path = Path(db_path)
        self._fernet: Fernet | None = None
        self._conn: sqlite3.Connection | None = None

    # -- lifecycle ----------------------------------------------------------

    def initialize(self, fernet: Fernet) -> None:
        """Open (or create) the database and verify the encryption key."""
        self._fernet = fernet
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_schema()
        self._verify_key()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # -- schema -------------------------------------------------------------

    def _create_schema(self) -> None:
        assert self._conn is not None
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS vault_meta (
                key   TEXT PRIMARY KEY,
                value BLOB NOT NULL
            );
            CREATE TABLE IF NOT EXISTS credentials (
                name       TEXT PRIMARY KEY,
                value      BLOB NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)

    # -- sentinel -----------------------------------------------------------

    def _verify_key(self) -> None:
        """Encrypt-or-check the sentinel to prove the key is correct."""
        from cryptography.fernet import InvalidToken

        assert self._conn is not None and self._fernet is not None

        row = self._conn.execute(
            "SELECT value FROM vault_meta WHERE key = 'sentinel'"
        ).fetchone()

        if row is None:
            # First initialisation — store encrypted sentinel.
            token = self._fernet.encrypt(_SENTINEL_PLAINTEXT)
            self._conn.execute(
                "INSERT INTO vault_meta (key, value) VALUES ('sentinel', ?)",
                (token,),
            )
            self._conn.commit()
        else:
            try:
                result = self._fernet.decrypt(row[0])
                if result != _SENTINEL_PLAINTEXT:
                    raise VaultKeyError("Sentinel mismatch — wrong encryption key.")
            except InvalidToken:
                raise VaultKeyError(
                    "Cannot decrypt vault — wrong encryption key or corrupted vault."
                ) from None

    # -- CRUD ---------------------------------------------------------------

    def get(self, name: str) -> str | None:
        from cryptography.fernet import InvalidToken

        assert self._conn is not None and self._fernet is not None

        row = self._conn.execute(
            "SELECT value FROM credentials WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            return None
        try:
            return self._fernet.decrypt(row[0]).decode("utf-8")
        except InvalidToken:
            raise VaultCorruptionError(
                f"Cannot decrypt credential '{name}'."
            ) from None

    def set(self, name: str, value: str) -> None:
        assert self._conn is not None and self._fernet is not None

        encrypted = self._fernet.encrypt(value.encode("utf-8"))
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """INSERT INTO credentials (name, value, created_at, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE
               SET value = excluded.value, updated_at = excluded.updated_at""",
            (name, encrypted, now, now),
        )
        self._conn.commit()

    def delete(self, name: str) -> bool:
        assert self._conn is not None
        cursor = self._conn.execute(
            "DELETE FROM credentials WHERE name = ?", (name,)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def list_names(self) -> list[str]:
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT name FROM credentials ORDER BY name"
        ).fetchall()
        return [r[0] for r in rows]

    def has(self, name: str) -> bool:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT 1 FROM credentials WHERE name = ?", (name,)
        ).fetchone()
        return row is not None

    def get_entry(self, name: str) -> CredentialEntry | None:
        from cryptography.fernet import InvalidToken

        assert self._conn is not None and self._fernet is not None

        row = self._conn.execute(
            "SELECT name, value, created_at, updated_at FROM credentials WHERE name = ?",
            (name,),
        ).fetchone()
        if row is None:
            return None
        try:
            decrypted = self._fernet.decrypt(row[1]).decode("utf-8")
        except InvalidToken:
            raise VaultCorruptionError(
                f"Cannot decrypt credential '{row[0]}'."
            ) from None
        return CredentialEntry(
            name=row[0],
            value=decrypted,
            created_at=datetime.fromisoformat(row[2]),
            updated_at=datetime.fromisoformat(row[3]),
        )
