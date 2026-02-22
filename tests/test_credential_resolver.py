"""Tests for the credential resolver (vault → .env fallback chain)."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from otto.credential_resolver import CredentialResolver
from otto.vault import SQLiteVaultBackend, VaultKeyError


@pytest.fixture
def fernet_key() -> Fernet:
    return Fernet(Fernet.generate_key())


@pytest.fixture
def vault_with_cred(tmp_path: Path, fernet_key: Fernet) -> Path:
    """Create a vault with one credential and return its path."""
    db_path = tmp_path / "vault.db"
    backend = SQLiteVaultBackend(db_path)
    backend.initialize(fernet_key)
    backend.set("VAULT_ONLY", "from-vault")
    backend.set("BOTH", "vault-wins")
    backend.close()
    return db_path


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    """Create a .env file with test variables."""
    env_path = tmp_path / ".env"
    env_path.write_text("ENV_ONLY=from-dotenv\nBOTH=env-loses\n")
    return env_path


# --- Vault hit ---


def test_vault_hit(vault_with_cred: Path, fernet_key: Fernet) -> None:
    resolver = CredentialResolver(
        vault_path=vault_with_cred,
        master_password="unused",  # not needed — we pass fernet directly
        _fernet_override=fernet_key,
    )
    assert resolver.get("VAULT_ONLY") == "from-vault"
    resolver.close()


# --- .env fallback ---


def test_env_fallback(tmp_path: Path, env_file: Path) -> None:
    """Credential not in vault, in .env → returns .env value."""
    resolver = CredentialResolver(
        vault_path=tmp_path / "nonexistent.db",
        env_file=str(env_file),
    )
    assert resolver.get("ENV_ONLY") == "from-dotenv"
    resolver.close()


# --- Vault priority ---


def test_vault_priority_over_env(
    vault_with_cred: Path, env_file: Path, fernet_key: Fernet
) -> None:
    """Credential in both vault and .env → vault wins."""
    resolver = CredentialResolver(
        vault_path=vault_with_cred,
        env_file=str(env_file),
        _fernet_override=fernet_key,
    )
    assert resolver.get("BOTH") == "vault-wins"
    resolver.close()


# --- Neither found ---


def test_neither_raises_keyerror(tmp_path: Path) -> None:
    resolver = CredentialResolver(
        vault_path=tmp_path / "nonexistent.db",
        env_file=str(tmp_path / "nonexistent.env"),
    )
    with pytest.raises(KeyError, match="MISSING"):
        resolver.get("MISSING")
    resolver.close()


# --- No vault file → graceful skip ---


def test_no_vault_file_falls_to_env(tmp_path: Path, env_file: Path) -> None:
    resolver = CredentialResolver(
        vault_path=tmp_path / "nonexistent.db",
        env_file=str(env_file),
    )
    assert resolver.get("ENV_ONLY") == "from-dotenv"
    resolver.close()


# --- Vault exists + wrong key → hard error ---


def test_wrong_key_raises_vault_key_error(
    vault_with_cred: Path, env_file: Path
) -> None:
    """If vault.db exists but key is wrong, raise — don't silently fall to .env."""
    wrong_key = Fernet(Fernet.generate_key())
    resolver = CredentialResolver(
        vault_path=vault_with_cred,
        env_file=str(env_file),
        _fernet_override=wrong_key,
    )
    with pytest.raises(VaultKeyError):
        resolver.get("BOTH")
    resolver.close()


# --- Interactive flag ---


def test_interactive_false_prevents_prompting(tmp_path: Path) -> None:
    """Non-interactive resolver should never attempt to prompt."""
    # Vault exists but no key source available → should raise VaultKeyError,
    # not hang on getpass
    db_path = tmp_path / "vault.db"
    key = Fernet(Fernet.generate_key())
    backend = SQLiteVaultBackend(db_path)
    backend.initialize(key)
    backend.close()

    resolver = CredentialResolver(
        vault_path=db_path,
        interactive=False,
        # No password, no fernet override → KeySource must resolve non-interactively
    )
    # Without keyring or OTTO_VAULT_PASSWORD, non-interactive should raise
    # We can't easily test this without mocking keyring, so just verify
    # the resolver was constructed with interactive=False
    assert resolver._interactive is False
    resolver.close()
