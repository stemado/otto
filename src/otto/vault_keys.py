"""Encryption key resolution for the credential vault.

Resolves the Fernet encryption key through a priority chain:

1. Explicit ``master_password`` argument
2. ``OTTO_VAULT_PASSWORD`` environment variable
3. OS keyring (Windows Credential Manager / macOS Keychain / Linux Secret Service)
4. Interactive ``getpass`` prompt (only when ``interactive=True``)

All imports of ``cryptography`` and ``keyring`` are lazy so the module
can be imported even when the optional ``vault`` extras are not installed.
"""

from __future__ import annotations

import base64
import getpass as _getpass_mod
import logging
import os
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cryptography.fernet import Fernet

from otto.vault import VaultKeyError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KEYRING_SERVICE = "otto-vault"
KEYRING_USERNAME = "encryption-key"
PBKDF2_ITERATIONS = 1_200_000


# ---------------------------------------------------------------------------
# Key resolution
# ---------------------------------------------------------------------------


class KeySource:
    """Resolves the Fernet encryption key for the vault."""

    @staticmethod
    def resolve(
        db_path: Path,
        master_password: str | None = None,
        *,
        interactive: bool = True,
    ) -> Fernet:
        """Resolve the encryption key using the priority chain.

        Parameters
        ----------
        db_path:
            Path to the SQLite vault database (needed for salt storage).
        master_password:
            Explicit password — takes highest priority.
        interactive:
            If ``False``, never prompt for input.  Raises ``VaultKeyError``
            when no key can be resolved non-interactively.
        """
        from cryptography.fernet import Fernet

        # 1. Explicit master password
        if master_password:
            return KeySource._derive_from_password(master_password, db_path)

        # 2. OTTO_VAULT_PASSWORD env var
        env_password = os.environ.get("OTTO_VAULT_PASSWORD")
        if env_password:
            return KeySource._derive_from_password(env_password, db_path)

        # 3. OS keyring
        try:
            import keyring  # type: ignore[import-untyped]

            stored = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
            if stored:
                return Fernet(stored.encode())

            # Keyring available but no key stored — generate one.
            key = Fernet.generate_key()
            keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, key.decode())
            return Fernet(key)
        except ImportError:
            logger.debug(
                "keyring not installed — skipping OS keyring. "
                "Install with: pip install 'otto[vault]'"
            )
        except Exception as exc:
            logger.debug("keyring backend error — skipping OS keyring: %s", exc)

        # 4. Interactive getpass prompt
        if interactive and os.isatty(0):
            password = _getpass_mod.getpass("Otto vault master password: ")
            if not password:
                raise VaultKeyError("Master password cannot be empty.")
            return KeySource._derive_from_password(password, db_path)

        # 5. Nothing worked.
        raise VaultKeyError(
            "No encryption key available. Set OTTO_VAULT_PASSWORD env var, "
            "install a keyring backend, or provide --password."
        )

    @staticmethod
    def _derive_from_password(password: str, db_path: Path) -> Fernet:
        """Derive a Fernet key from a master password via PBKDF2.

        The 16-byte salt is stored in / read from the ``vault_meta`` table
        in the SQLite database at *db_path*.
        """
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

        salt = KeySource._get_or_create_salt(db_path)

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=PBKDF2_ITERATIONS,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return Fernet(key)

    @staticmethod
    def _get_or_create_salt(db_path: Path) -> bytes:
        """Read the PBKDF2 salt from vault_meta, or generate and store one."""
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vault_meta (
                key   TEXT PRIMARY KEY,
                value BLOB NOT NULL
            )
        """)

        row = conn.execute(
            "SELECT value FROM vault_meta WHERE key = 'pbkdf2_salt'"
        ).fetchone()

        if row is not None:
            conn.close()
            return bytes.fromhex(row[0])

        salt = os.urandom(16)
        conn.execute(
            "INSERT INTO vault_meta (key, value) VALUES ('pbkdf2_salt', ?)",
            (salt.hex(),),
        )
        conn.commit()
        conn.close()
        return salt
