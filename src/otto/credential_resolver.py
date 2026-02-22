"""Unified credential resolver with vault-first, .env fallback.

Resolution order:
    1. Encrypted SQLite vault (primary)
    2. ``.env`` file (legacy fallback)
    3. ``KeyError``

All vault-related imports are lazy so this module works even when the
optional ``vault`` extras (``cryptography``, ``keyring``) are not installed.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from .secrets import EnvLoadError, load_env_vars

if TYPE_CHECKING:
    from cryptography.fernet import Fernet

    from .vault import SQLiteVaultBackend

# Default vault location (same as vault.py)
_DEFAULT_VAULT_PATH = Path.home() / ".otto" / "vault.db"


class CredentialSource(Enum):
    """Where a credential was resolved from."""

    VAULT = "vault"
    ENV = "env"


class ResolvedCredential(NamedTuple):
    """A credential value paired with its source."""

    value: str
    source: CredentialSource


class CredentialResolver:
    """Resolves credentials from vault (primary) with .env fallback.

    Parameters
    ----------
    vault_path:
        Path to the SQLite vault database.
    env_file:
        Explicit path to a ``.env`` file (uses the default search order
        from ``otto.secrets`` if ``None``).
    master_password:
        Explicit password for vault key derivation.
    interactive:
        If ``False``, never prompt for a vault password.
    _fernet_override:
        Inject a Fernet key directly (for testing).
    """

    def __init__(
        self,
        vault_path: Path | str = _DEFAULT_VAULT_PATH,
        env_file: str | None = None,
        master_password: str | None = None,
        *,
        interactive: bool = True,
        _fernet_override: Fernet | None = None,
    ) -> None:
        self._vault_path = Path(vault_path)
        self._env_file = env_file
        self._master_password = master_password
        self._interactive = interactive
        self._fernet_override = _fernet_override

        self._vault: SQLiteVaultBackend | None = None
        self._env_vars: dict[str, str] | None = None
        self._vault_initialized = False
        self._env_loaded = False

    def get(self, name: str) -> str:
        """Resolve a credential by name.

        Raises ``KeyError`` if not found in vault or .env.
        Raises ``VaultKeyError`` if the vault exists but cannot be decrypted.
        """
        return self.get_with_source(name).value

    def get_with_source(self, name: str) -> ResolvedCredential:
        """Resolve a credential and report where it came from.

        Returns a ``ResolvedCredential(value, source)`` tuple.
        Raises ``KeyError`` if not found in vault or .env.
        Raises ``VaultKeyError`` if the vault exists but cannot be decrypted.
        """
        # Try vault first
        vault_value = self._try_vault(name)
        if vault_value is not None:
            return ResolvedCredential(vault_value, CredentialSource.VAULT)

        # Fall back to .env
        env_value = self._try_env(name)
        if env_value is not None:
            return ResolvedCredential(env_value, CredentialSource.ENV)

        raise KeyError(
            f"Credential '{name}' not found in vault or .env file."
        )

    def _try_vault(self, name: str) -> str | None:
        """Read from vault.  Raises ``VaultKeyError`` on wrong key."""
        if not self._vault_initialized:
            self._init_vault()
        if self._vault is None:
            return None
        return self._vault.get(name)

    def _try_env(self, name: str) -> str | None:
        """Read from .env.  Returns ``None`` if .env unavailable."""
        if not self._env_loaded:
            self._init_env()
        if self._env_vars is None:
            return None
        return self._env_vars.get(name)

    def _init_vault(self) -> None:
        """Lazily open the vault.  Skips silently if vault file doesn't exist."""
        self._vault_initialized = True

        if not self._vault_path.exists():
            return

        try:
            from .vault import SQLiteVaultBackend
            from .vault_keys import KeySource
        except ImportError:
            # cryptography not installed — vault unavailable
            return

        if self._fernet_override is not None:
            fernet = self._fernet_override
        else:
            fernet = KeySource.resolve(
                self._vault_path,
                master_password=self._master_password,
                interactive=self._interactive,
            )

        backend = SQLiteVaultBackend(self._vault_path)
        backend.initialize(fernet)  # raises VaultKeyError on wrong key
        self._vault = backend

    def _init_env(self) -> None:
        """Lazily load .env variables."""
        self._env_loaded = True
        try:
            self._env_vars = load_env_vars(self._env_file)
        except EnvLoadError:
            self._env_vars = None

    def close(self) -> None:
        """Release backend resources."""
        if self._vault:
            self._vault.close()
            self._vault = None
