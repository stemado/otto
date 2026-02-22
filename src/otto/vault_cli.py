"""CLI for managing the Otto encrypted credential vault.

Usage::

    otto-vault set NAME [VALUE]          # store (prompted if value omitted)
    otto-vault get NAME                  # retrieve
    otto-vault remove NAME               # delete
    otto-vault list                      # show all names
    otto-vault import-env [--env-file X] # bulk import from .env
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from .secrets import EnvLoadError, load_env_vars
from .vault import DEFAULT_VAULT_PATH, SQLiteVaultBackend
from .vault_keys import KeySource


def _open_vault(args: argparse.Namespace) -> SQLiteVaultBackend:
    """Open (or create) the vault with the resolved encryption key."""
    db_path = Path(args.vault) if args.vault else DEFAULT_VAULT_PATH
    password = getattr(args, "password", None)
    fernet = KeySource.resolve(db_path, master_password=password)
    backend = SQLiteVaultBackend(db_path)
    backend.initialize(fernet)
    return backend


def cmd_set(args: argparse.Namespace) -> None:
    vault = _open_vault(args)
    value = args.value
    if value is None:
        value = getpass.getpass(f"Value for '{args.name}': ")
    vault.set(args.name, value)
    print(f"Stored '{args.name}' in vault.")
    vault.close()


def cmd_get(args: argparse.Namespace) -> None:
    vault = _open_vault(args)
    value = vault.get(args.name)
    if value is None:
        print(f"Not found: '{args.name}'", file=sys.stderr)
        vault.close()
        sys.exit(1)
    print(value)
    vault.close()


def cmd_remove(args: argparse.Namespace) -> None:
    vault = _open_vault(args)
    if vault.delete(args.name):
        print(f"Removed '{args.name}' from vault.")
    else:
        print(f"Not found: '{args.name}'", file=sys.stderr)
        vault.close()
        sys.exit(1)
    vault.close()


def cmd_list(args: argparse.Namespace) -> None:
    vault = _open_vault(args)
    names = vault.list_names()
    if not names:
        print("Vault is empty.")
    else:
        for name in names:
            print(name)
    vault.close()


def cmd_init(args: argparse.Namespace) -> None:
    """Guided setup: create vault, test encryption, optionally import .env."""
    db_path = Path(args.vault) if args.vault else DEFAULT_VAULT_PATH

    if db_path.exists():
        print(f"Vault already exists at {db_path}")
        # Verify we can open it
        vault = _open_vault(args)
        count = len(vault.list_names())
        vault.close()
        print(f"  Contains {count} credential(s). Ready to use.")
        return

    print(f"Creating encrypted vault at {db_path}")
    print()

    # Create the vault (key resolution happens here — keyring or password)
    vault = _open_vault(args)

    # Verify round-trip encryption works
    vault.set("__otto_init_test__", "ok")
    assert vault.get("__otto_init_test__") == "ok"
    vault.delete("__otto_init_test__")
    print("  Encryption verified.")

    # Check for .env and offer to import
    try:
        env_vars = load_env_vars()
        count = len(env_vars)
        if count > 0:
            print(f"  Found .env with {count} variable(s).")
            answer = input("  Import them into the vault? [Y/n] ").strip().lower()
            if answer in ("", "y", "yes"):
                imported = 0
                for name, value in sorted(env_vars.items()):
                    vault.set(name, value)
                    print(f"    imported: {name}")
                    imported += 1
                print(f"  Imported {imported} credential(s).")
            else:
                print("  Skipped .env import.")
    except EnvLoadError:
        print("  No .env file found (that's fine — add credentials with 'otto-vault set').")

    vault.close()
    print()
    print("Vault is ready. fill_secret will now use the vault automatically.")
    print("Manage credentials with: otto-vault set|get|list|remove")


def cmd_import_env(args: argparse.Namespace) -> None:
    vault = _open_vault(args)
    env_file = getattr(args, "env_file", None)
    try:
        env_vars = load_env_vars(env_file)
    except EnvLoadError as e:
        print(str(e), file=sys.stderr)
        vault.close()
        sys.exit(1)

    imported = 0
    skipped = 0
    for name, value in sorted(env_vars.items()):
        if vault.has(name) and not args.force:
            print(f"  skip: {name} (already in vault, use --force to overwrite)")
            skipped += 1
        else:
            vault.set(name, value)
            print(f"  imported: {name}")
            imported += 1

    print(f"\nImported {imported}, skipped {skipped}.")
    vault.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="otto-vault",
        description="Manage the Otto encrypted credential vault",
    )
    parser.add_argument(
        "--vault",
        help=f"Vault path (default: {DEFAULT_VAULT_PATH})",
    )
    parser.add_argument(
        "--password",
        help="Master password (alternative to keyring)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = sub.add_parser("init", help="Create and set up a new vault")
    p_init.set_defaults(func=cmd_init)

    # set
    p_set = sub.add_parser("set", help="Store a credential")
    p_set.add_argument("name", help="Credential name (e.g., APP_PASSWORD)")
    p_set.add_argument("value", nargs="?", help="Value (prompted if omitted)")
    p_set.set_defaults(func=cmd_set)

    # get
    p_get = sub.add_parser("get", help="Retrieve a credential value")
    p_get.add_argument("name", help="Credential name")
    p_get.set_defaults(func=cmd_get)

    # remove
    p_rm = sub.add_parser("remove", help="Delete a credential")
    p_rm.add_argument("name", help="Credential name")
    p_rm.set_defaults(func=cmd_remove)

    # list
    p_list = sub.add_parser("list", help="List all credential names")
    p_list.set_defaults(func=cmd_list)

    # import-env
    p_import = sub.add_parser(
        "import-env", help="Import credentials from a .env file"
    )
    p_import.add_argument(
        "--env-file", help="Path to .env file (uses default search if omitted)"
    )
    p_import.add_argument(
        "--force", action="store_true", help="Overwrite existing vault entries"
    )
    p_import.set_defaults(func=cmd_import_env)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
