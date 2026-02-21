"""Tests for otto.secrets -- .env loading with search order."""

from __future__ import annotations

from pathlib import Path

import pytest

from otto.secrets import EnvLoadError, load_env_vars


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def env_file(tmp_path: Path) -> Path:
    """Create a basic .env file in a temp directory and return its path."""
    p = tmp_path / ".env"
    p.write_text(
        "DB_HOST=localhost\n"
        "DB_PORT=5432\n"
        "API_KEY=abc123\n"
    )
    return p


@pytest.fixture()
def env_file_with_quotes(tmp_path: Path) -> Path:
    """Create a .env file with quoted values."""
    p = tmp_path / ".env"
    p.write_text(
        'SINGLE_QUOTED=\'hello world\'\n'
        'DOUBLE_QUOTED="goodbye world"\n'
        "UNQUOTED=plain\n"
    )
    return p


@pytest.fixture()
def env_file_with_comments(tmp_path: Path) -> Path:
    """Create a .env file with comments and blank lines."""
    p = tmp_path / ".env"
    p.write_text(
        "# This is a comment\n"
        "\n"
        "REAL_VAR=real_value\n"
        "  # indented comment\n"
        "ANOTHER=value\n"
    )
    return p


@pytest.fixture()
def env_file_with_empty_values(tmp_path: Path) -> Path:
    """Create a .env file with empty values."""
    p = tmp_path / ".env"
    p.write_text(
        "PRESENT=hello\n"
        "EMPTY=\n"
        "ALSO_EMPTY=\n"
    )
    return p


# ---------------------------------------------------------------------------
# Basic loading
# ---------------------------------------------------------------------------


def test_load_basic_key_value(env_file: Path) -> None:
    """load_env_vars returns a dict of key=value pairs from a .env file."""
    result = load_env_vars(str(env_file))
    assert result == {
        "DB_HOST": "localhost",
        "DB_PORT": "5432",
        "API_KEY": "abc123",
    }


def test_load_strips_quotes(env_file_with_quotes: Path) -> None:
    """Quoted values have their surrounding quotes stripped."""
    result = load_env_vars(str(env_file_with_quotes))
    assert result["SINGLE_QUOTED"] == "hello world"
    assert result["DOUBLE_QUOTED"] == "goodbye world"
    assert result["UNQUOTED"] == "plain"


def test_load_empty_values(env_file_with_empty_values: Path) -> None:
    """Empty values are normalized to empty strings (not None)."""
    result = load_env_vars(str(env_file_with_empty_values))
    assert result["PRESENT"] == "hello"
    assert result["EMPTY"] == ""
    assert result["ALSO_EMPTY"] == ""


def test_load_skips_comments(env_file_with_comments: Path) -> None:
    """Comments and blank lines are ignored; only real vars are returned."""
    result = load_env_vars(str(env_file_with_comments))
    assert result == {
        "REAL_VAR": "real_value",
        "ANOTHER": "value",
    }


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_error_when_file_does_not_exist() -> None:
    """Raises EnvLoadError when the explicit path doesn't exist."""
    with pytest.raises(EnvLoadError, match="not found"):
        load_env_vars("/nonexistent/path/.env")


def test_error_when_no_env_anywhere(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Raises EnvLoadError when no .env file can be found via any search path."""
    monkeypatch.delenv("OTTO_ENV_FILE", raising=False)
    monkeypatch.chdir(tmp_path)  # empty directory, no .env
    with pytest.raises(EnvLoadError, match="No .env file found"):
        load_env_vars()


# ---------------------------------------------------------------------------
# Search order
# ---------------------------------------------------------------------------


def test_env_var_overrides_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OTTO_ENV_FILE env var takes precedence over cwd .env."""
    # Create .env in cwd with one value
    cwd_env = tmp_path / "cwd"
    cwd_env.mkdir()
    (cwd_env / ".env").write_text("SOURCE=cwd\n")

    # Create .env at a custom path with a different value
    custom_env = tmp_path / "custom" / ".env"
    custom_env.parent.mkdir()
    custom_env.write_text("SOURCE=env_var\n")

    monkeypatch.chdir(cwd_env)
    monkeypatch.setenv("OTTO_ENV_FILE", str(custom_env))

    result = load_env_vars()
    assert result["SOURCE"] == "env_var"


def test_falls_back_to_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Falls back to .env in cwd when no explicit path or env var is set."""
    (tmp_path / ".env").write_text("SOURCE=cwd_fallback\n")
    monkeypatch.delenv("OTTO_ENV_FILE", raising=False)
    monkeypatch.chdir(tmp_path)

    result = load_env_vars()
    assert result["SOURCE"] == "cwd_fallback"


def test_explicit_path_takes_highest_priority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit env_file argument beats OTTO_ENV_FILE and cwd."""
    # Setup env var pointing to one file
    env_var_file = tmp_path / "via_env_var" / ".env"
    env_var_file.parent.mkdir()
    env_var_file.write_text("SOURCE=env_var\n")
    monkeypatch.setenv("OTTO_ENV_FILE", str(env_var_file))

    # Setup cwd with another file
    cwd_dir = tmp_path / "cwd"
    cwd_dir.mkdir()
    (cwd_dir / ".env").write_text("SOURCE=cwd\n")
    monkeypatch.chdir(cwd_dir)

    # Setup explicit file
    explicit_file = tmp_path / "explicit" / ".env"
    explicit_file.parent.mkdir()
    explicit_file.write_text("SOURCE=explicit\n")

    result = load_env_vars(str(explicit_file))
    assert result["SOURCE"] == "explicit"


# ---------------------------------------------------------------------------
# EnvLoadError is a proper exception
# ---------------------------------------------------------------------------


def test_env_load_error_is_exception() -> None:
    """EnvLoadError is a standard Exception subclass."""
    err = EnvLoadError("something went wrong")
    assert isinstance(err, Exception)
    assert str(err) == "something went wrong"
