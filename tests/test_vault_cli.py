"""Tests for the otto-vault CLI commands."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from otto.vault import SQLiteVaultBackend
from otto.vault_cli import main as vault_main


def _run_vault_cli(
    *args: str, vault_path: Path, password: str = "testpass"
) -> subprocess.CompletedProcess[str]:
    """Run the vault CLI as a subprocess."""
    return subprocess.run(
        [
            sys.executable, "-m", "otto.vault_cli",
            "--vault", str(vault_path),
            "--password", password,
            *args,
        ],
        capture_output=True,
        text=True,
    )


# --- set / get roundtrip ---


def test_set_and_get_roundtrip(tmp_path: Path) -> None:
    db_path = tmp_path / "vault.db"
    result = _run_vault_cli("set", "MY_KEY", "my-value", vault_path=db_path)
    assert result.returncode == 0
    assert "Stored" in result.stdout

    result = _run_vault_cli("get", "MY_KEY", vault_path=db_path)
    assert result.returncode == 0
    assert result.stdout.strip() == "my-value"


# --- list ---


def test_list_empty_vault(tmp_path: Path) -> None:
    db_path = tmp_path / "vault.db"
    # First set something to create the vault, then remove it
    _run_vault_cli("set", "TEMP", "x", vault_path=db_path)
    _run_vault_cli("remove", "TEMP", vault_path=db_path)

    result = _run_vault_cli("list", vault_path=db_path)
    assert result.returncode == 0
    assert "empty" in result.stdout.lower()


def test_list_shows_names(tmp_path: Path) -> None:
    db_path = tmp_path / "vault.db"
    _run_vault_cli("set", "ALPHA", "a", vault_path=db_path)
    _run_vault_cli("set", "BETA", "b", vault_path=db_path)

    result = _run_vault_cli("list", vault_path=db_path)
    assert result.returncode == 0
    lines = result.stdout.strip().splitlines()
    assert "ALPHA" in lines
    assert "BETA" in lines
    # Values should NOT appear
    assert "a" not in result.stdout or "ALPHA" in result.stdout  # "a" is in "ALPHA"
    assert "b" not in result.stdout or "BETA" in result.stdout


# --- remove ---


def test_remove_existing(tmp_path: Path) -> None:
    db_path = tmp_path / "vault.db"
    _run_vault_cli("set", "KEY", "val", vault_path=db_path)
    result = _run_vault_cli("remove", "KEY", vault_path=db_path)
    assert result.returncode == 0
    assert "Removed" in result.stdout


def test_remove_nonexistent_exits_1(tmp_path: Path) -> None:
    db_path = tmp_path / "vault.db"
    # Create vault by setting something first
    _run_vault_cli("set", "TEMP", "x", vault_path=db_path)
    result = _run_vault_cli("remove", "NOPE", vault_path=db_path)
    assert result.returncode == 1
    assert "Not found" in result.stderr


# --- get nonexistent ---


def test_get_nonexistent_exits_1(tmp_path: Path) -> None:
    db_path = tmp_path / "vault.db"
    _run_vault_cli("set", "TEMP", "x", vault_path=db_path)
    result = _run_vault_cli("get", "NOPE", vault_path=db_path)
    assert result.returncode == 1
    assert "Not found" in result.stderr


# --- import-env ---


def test_import_env_basic(tmp_path: Path) -> None:
    db_path = tmp_path / "vault.db"
    env_file = tmp_path / ".env"
    env_file.write_text("IMPORTED_KEY=imported-value\nANOTHER=foo\n")

    result = _run_vault_cli(
        "import-env", "--env-file", str(env_file), vault_path=db_path
    )
    assert result.returncode == 0
    assert "imported: IMPORTED_KEY" in result.stdout
    assert "imported: ANOTHER" in result.stdout

    # Verify the values are in the vault
    result = _run_vault_cli("get", "IMPORTED_KEY", vault_path=db_path)
    assert result.stdout.strip() == "imported-value"


def test_import_env_skip_existing(tmp_path: Path) -> None:
    db_path = tmp_path / "vault.db"
    env_file = tmp_path / ".env"
    env_file.write_text("KEY=env-value\n")

    # Pre-populate vault
    _run_vault_cli("set", "KEY", "vault-value", vault_path=db_path)

    result = _run_vault_cli(
        "import-env", "--env-file", str(env_file), vault_path=db_path
    )
    assert result.returncode == 0
    assert "skip" in result.stdout.lower()

    # Vault value should be unchanged
    result = _run_vault_cli("get", "KEY", vault_path=db_path)
    assert result.stdout.strip() == "vault-value"


# --- init ---


def test_init_creates_vault(tmp_path: Path) -> None:
    db_path = tmp_path / "vault.db"
    result = _run_vault_cli("init", vault_path=db_path)
    assert result.returncode == 0
    assert "Creating encrypted vault" in result.stdout
    assert "Encryption verified" in result.stdout
    assert db_path.exists()


def test_init_existing_vault(tmp_path: Path) -> None:
    db_path = tmp_path / "vault.db"
    _run_vault_cli("set", "KEY", "val", vault_path=db_path)

    result = _run_vault_cli("init", vault_path=db_path)
    assert result.returncode == 0
    assert "already exists" in result.stdout


def test_import_env_force_overwrite(tmp_path: Path) -> None:
    db_path = tmp_path / "vault.db"
    env_file = tmp_path / ".env"
    env_file.write_text("KEY=env-value\n")

    _run_vault_cli("set", "KEY", "vault-value", vault_path=db_path)

    result = _run_vault_cli(
        "import-env", "--env-file", str(env_file), "--force", vault_path=db_path
    )
    assert result.returncode == 0
    assert "imported: KEY" in result.stdout

    result = _run_vault_cli("get", "KEY", vault_path=db_path)
    assert result.stdout.strip() == "env-value"
