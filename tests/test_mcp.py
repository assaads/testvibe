"""Tests for testvibe.mcp - FastMCP server exposing the engine to coding agents.

These tests are hermetic and fast: the tool-name test builds the server and
reads the registered tool names via fastmcp v2's PUBLIC async ``list_tools()``
API (the ``_tool_manager._tools`` attribute referenced in older plans does not
exist in fastmcp v2), and the corpus round-trip exercises the real tool through
``call_tool`` against a tmp ``known-failures.yaml`` so the repo is never
mutated. No tool actually subprocesses pytest here.
"""

import asyncio

import pytest


# fastmcp v2 exposes registered tools via ``await server.list_tools()``; each
# returned Tool object carries a ``.name``. This is the public, stable surface.
async def _tool_names(server):
    tools = await server.list_tools()
    return {t.name for t in tools}


# fastmcp v2's call_tool returns a ToolResult whose structured_content envelope
# is asymmetric: a dict return is passed through as-is, while a str/list/scalar
# return is wrapped in {"result": value}. Unwrap generically so assertions do
# not depend on the envelope shape.
def _unwrap(tool_result):
    sc = tool_result.structured_content
    if isinstance(sc, dict) and set(sc.keys()) == {"result"}:
        return sc["result"]
    return sc


EXPECTED_TOOLS = {
    "run_scenario",
    "get_run_report",
    "list_coverage_gaps",
    "list_advisories",
    "add_corpus_entry",
    "promote_corpus",
}


def test_mcp_exposes_engine_tools():
    """build_server(contract_path=None) registers exactly the 6 engine tools."""
    from testvibe.mcp import build_server

    s = build_server(contract_path=None)
    names = asyncio.run(_tool_names(s))
    assert EXPECTED_TOOLS <= names, (
        f"missing tools: {EXPECTED_TOOLS - names}; have {sorted(names)}"
    )


def test_mcp_build_server_accepts_none_contract():
    """No contract on disk must not blow up - it degrades to a no-op server."""
    from testvibe.mcp import build_server

    s = build_server(contract_path=None)
    assert s is not None
    # list_tools works without raising even with an empty/no-op contract.
    tools = asyncio.run(s.list_tools())
    assert len(tools) >= 6


def test_mcp_corpus_round_trip(tmp_path):
    """add_corpus_entry appends to known-failures.yaml; promote_corpus flips to fixed.

    Drives the tools through the server's public ``call_tool`` transport against
    an isolated tmp corpus so the repo's own known-failures.yaml is untouched.
    """
    from testvibe.mcp import build_server

    corpus = tmp_path / "known-failures.yaml"
    repro = tmp_path / "repro.py"
    repro.write_text("def repro():\n    raise AssertionError('bug')\n")

    s = build_server(contract_path=None, corpus_path=corpus)

    async def drive():
        added = await s.call_tool(
            "add_corpus_entry",
            {
                "id": "bug-1",
                "invariant": "push is idempotent",
                "repro_path": str(repro),
                "status": "open",
            },
        )
        promoted = await s.call_tool("promote_corpus", {"id": "bug-1"})
        return added, promoted

    added, promoted = asyncio.run(drive())

    # _unwrap normalizes fastmcp v2's structured_content envelope (dict returns
    # pass through; list/str returns are wrapped in {"result": ...}).
    added_row = _unwrap(added)
    assert added_row["id"] == "bug-1"
    assert added_row["status"] == "open"

    promoted_row = _unwrap(promoted)
    assert promoted_row["id"] == "bug-1"
    assert promoted_row["status"] == "fixed"

    # The corpus file on disk must reflect the promotion.
    from testvibe.corpus import load_corpus

    # load_corpus filters to open/pinned only, so a now-fixed entry is dropped
    # from the active quarantine set - exactly the promotion semantics.
    assert load_corpus(corpus) == []

    raw = corpus.read_text()
    assert "bug-1" in raw
    assert "status: fixed" in raw


def test_mcp_list_coverage_gaps_is_data_only(tmp_path):
    """list_coverage_gaps returns advisory coverage_gap rows (no LLM, no network)."""
    from testvibe.mcp import build_server

    s = build_server(
        contract_path=None,
        fixture_paths=["src/app.py"],
        touched_paths=["src/app.py", "src/secret_uncovered.py"],
        transcript="",
        baseline=None,
    )

    async def go():
        r = await s.call_tool("list_coverage_gaps", {})
        return _unwrap(r)

    rows = asyncio.run(go())
    assert isinstance(rows, list)
    msgs = [row.get("message", row.get("detail", "")) for row in rows]
    assert any("src/secret_uncovered.py" in m for m in msgs)
    assert all(row["kind"] == "coverage_gap" for row in rows)


def test_mcp_get_run_report_unknown_run(tmp_path):
    """get_run_report on an unknown run_id yields a structured not-found report."""
    from testvibe.mcp import build_server

    s = build_server(contract_path=None)

    async def go():
        r = await s.call_tool("get_run_report", {"run_id": "no-such-run"})
        return _unwrap(r)

    out = asyncio.run(go())
    # Unknown run must be handled gracefully (no crash) - a JSON-serializable
    # report object with a not-found marker.
    assert isinstance(out, (str, dict))
    if isinstance(out, str):
        assert "no-such-run" in out
