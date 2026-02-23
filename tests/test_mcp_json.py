"""Test that .mcp.json includes vault extra for the MCP server."""

from __future__ import annotations

import json
from pathlib import Path


def test_mcp_json_includes_vault_extra() -> None:
    """The uv args must include --extra vault so keyring is available."""
    mcp_path = Path(__file__).resolve().parent.parent / ".mcp.json"
    config = json.loads(mcp_path.read_text())

    args = config["mcpServers"]["otto"]["args"]

    # --extra and vault must appear as consecutive elements
    assert "--extra" in args, "Missing --extra flag in .mcp.json args"
    extra_idx = args.index("--extra")
    assert extra_idx + 1 < len(args), "--extra flag has no value"
    assert args[extra_idx + 1] == "vault", (
        f"Expected --extra vault, got --extra {args[extra_idx + 1]}"
    )
