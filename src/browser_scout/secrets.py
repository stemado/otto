"""Load environment variables from .env files with a defined search order.

Search order for the .env file:
    1. Explicit ``env_file`` path (if provided to :func:`load_env_vars`)
    2. ``BROWSER_SCOUT_ENV_FILE`` environment variable
    3. ``.env`` in the current working directory

Uses ``python-dotenv``'s :func:`dotenv_values` for parsing.
None values (keys with no ``=`` sign) are normalised to empty strings.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values


class EnvLoadError(Exception):
    """Raised when the .env file cannot be located or loaded."""


def _resolve_env_path(env_file: str | None = None) -> Path:
    """Determine which .env file to load using the three-level search order.

    Raises :class:`EnvLoadError` if no file can be found.
    """
    # 1. Explicit path
    if env_file is not None:
        p = Path(env_file)
        if not p.is_file():
            raise EnvLoadError(f".env file not found: {p}")
        return p

    # 2. BROWSER_SCOUT_ENV_FILE env var
    env_var = os.environ.get("BROWSER_SCOUT_ENV_FILE")
    if env_var:
        p = Path(env_var)
        if not p.is_file():
            raise EnvLoadError(f".env file not found: {p}")
        return p

    # 3. .env in current working directory
    cwd_env = Path.cwd() / ".env"
    if cwd_env.is_file():
        return cwd_env

    raise EnvLoadError(
        "No .env file found. Searched: BROWSER_SCOUT_ENV_FILE env var, "
        f".env in cwd ({Path.cwd()})"
    )


def load_env_vars(env_file: str | None = None) -> dict[str, str]:
    """Load variables from a ``.env`` file and return them as a dict.

    Parameters
    ----------
    env_file:
        Explicit path to a ``.env`` file.  When ``None``, the search order
        described in the module docstring is used.

    Returns
    -------
    dict[str, str]
        Mapping of variable names to their string values.  Values that
        ``python-dotenv`` reports as ``None`` are normalised to ``""``.

    Raises
    ------
    EnvLoadError
        If no ``.env`` file can be found at any of the search locations.
    """
    path = _resolve_env_path(env_file)
    raw = dotenv_values(path)
    return {key: (value if value is not None else "") for key, value in raw.items()}
