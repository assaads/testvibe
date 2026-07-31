"""Shared transport helper for the self-dogfood ``scenarios/`` suite.

The MCP ``_unwrap`` helper normalizes the fastmcp v2/v3 ``call_tool``
structured-content envelope so assertions do not depend on that asymmetric
shape. It mirrors the pattern in ``tests/test_mcp.py``.
"""

from __future__ import annotations

from typing import Any


def _unwrap(tool_result: Any) -> Any:
    """Unwrap a fastmcp v2/v3 ``call_tool`` result generically.

    A dict return is passed through as-is; a str/list/scalar is wrapped in
    ``{"result": value}``. Mirrors ``tests/test_mcp.py`` so assertions do not
    depend on the asymmetric structured-content envelope.
    """
    sc = getattr(tool_result, "structured_content", tool_result)
    if isinstance(sc, dict) and set(sc.keys()) == {"result"}:
        return sc["result"]
    return sc
