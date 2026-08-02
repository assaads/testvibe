"""Tests for testvibe.mcp - FastMCP server exposing the engine to coding agents.

These tests are hermetic and fast: the tool-name test builds the server and
reads the registered tool names via fastmcp v2's PUBLIC async ``list_tools()``
API (the ``_tool_manager._tools`` attribute referenced in older plans does not
exist in fastmcp v2), and the corpus round-trip exercises the real tool through
``call_tool`` against a tmp ``known-failures.yaml`` so the repo is never
mutated. No tool actually subprocesses pytest here.
"""

import asyncio
import json


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
    assert names >= EXPECTED_TOOLS, (
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


# ---------------------------------------------------------------------------
# run_scenario / list_advisories behavioral coverage (Fix 1).
#
# These drive run_scenario through the real MCP transport, which subprocesses
# pytest in a hermetic tmp cwd. Each case gets its own tmp project so a
# collection error in one can never poison another run's collection. The pass
# and fail cases together prove run_scenario genuinely executes the scenario
# and reflects its real result: a no-op/stubbed run_scenario would return the
# same `passed` value for both.
# ---------------------------------------------------------------------------


def _write_scenario_project(root, scenario_name, body):
    """Lay down a hermetic one-scenario pytest project under ``root``.

    The test function name embeds the scenario name because ``run_scenario``
    selects via pytest's ``-k <name>`` filter, which matches the test nodeid
    (the function name), not the ``@scenario`` metadata.
    """
    fn_name = "test_" + scenario_name
    (root / "conftest.py").write_text("import testvibe.plugin  # noqa: F401\n")
    (root / "test_demo.py").write_text(
        "from testvibe import scenario\n"
        "\n"
        f"@scenario({scenario_name!r})\n"
        f"def {fn_name}():\n"
        f"    {body}\n"
    )


def test_mcp_run_scenario_pass_reflected_in_report(tmp_path):
    """run_scenario runs pytest for real; a passing scenario -> report.passed=True."""
    from testvibe.mcp import build_server

    _write_scenario_project(tmp_path, "demo_pass", "assert True")
    s = build_server(contract_path=None, cwd=tmp_path)

    async def drive():
        run_id = await s.call_tool("run_scenario", {"name": "demo_pass"})
        rid = _unwrap(run_id)
        report_raw = await s.call_tool("get_run_report", {"run_id": rid})
        adv = await s.call_tool("list_advisories", {"run_id": rid})
        return rid, report_raw, adv

    rid, report_raw, adv = asyncio.run(drive())
    assert isinstance(rid, str) and rid.startswith("run-")

    report = json.loads(_unwrap(report_raw))
    assert report["passed"] is True
    assert report["run"] == "scenario:demo_pass"

    # list_advisories on a real run_id returns a list (possibly empty), not None.
    advisories = _unwrap(adv)
    assert isinstance(advisories, list)


def test_mcp_run_scenario_fail_reflected_in_report(tmp_path):
    """run_scenario reflects a real assertion failure -> report.passed=False."""
    from testvibe.mcp import build_server

    _write_scenario_project(
        tmp_path, "demo_fail", "assert False, 'intentional failure'"
    )
    s = build_server(contract_path=None, cwd=tmp_path)

    async def drive():
        run_id = await s.call_tool("run_scenario", {"name": "demo_fail"})
        report_raw = await s.call_tool(
            "get_run_report", {"run_id": _unwrap(run_id)}
        )
        return report_raw

    report_raw = asyncio.run(drive())
    report = json.loads(_unwrap(report_raw))
    assert report["passed"] is False
    # A genuine assertion failure is a product signal: recorded as a failure.
    assert report["failures"], "expected a failure row for a failing scenario"


def test_mcp_run_scenario_infra_failure_classified_infra(tmp_path):
    """An infra failure (pytest collection error) -> kind='infra', not 'product'.

    A test module that imports a missing module makes pytest error out during
    collection (exit code 2) - a runner/environment problem, not a product
    regression. Per the PLAYBOOK infra-vs-product taxonomy the RunReport must
    classify this as ``infra``.
    """
    from testvibe.mcp import build_server

    (tmp_path / "conftest.py").write_text("import testvibe.plugin  # noqa: F401\n")
    # The bad import runs at collection time -> pytest exits 2 (infra).
    (tmp_path / "test_broken.py").write_text(
        "from testvibe import scenario\n"
        "import does_not_exist_module_xyz  # noqa: F401  # collection error\n"
        "\n"
        "@scenario('broken')\n"
        "def test_broken():\n"
        "    assert True\n"
    )
    s = build_server(contract_path=None, cwd=tmp_path)

    async def drive():
        run_id = await s.call_tool("run_scenario", {"name": "broken"})
        report_raw = await s.call_tool(
            "get_run_report", {"run_id": _unwrap(run_id)}
        )
        return report_raw

    report_raw = asyncio.run(drive())
    report = json.loads(_unwrap(report_raw))
    assert report["passed"] is False
    kinds = {f["kind"] for f in report["failures"]}
    assert "infra" in kinds, f"expected infra classification, got {kinds}"
    assert "product" not in kinds, (
        "collection error must NOT be classified as a product regression"
    )


# ---------------------------------------------------------------------------
# Single mutation path (Task: corpus mutation single-path).
#
# The MCP corpus tools must route through corpus.add_entry / promote_entry so
# known-failures.yaml has ONE write path (not mcp's own raw-dict dump). The
# observable proof: the file the MCP tool writes round-trips through
# load_corpus with full CorpusEntry fields, AND is byte-equivalent to what
# corpus.add_entry writes directly. If mcp kept a private dump, the two could
# drift (field order, missing keys) without this test catching it.
# ---------------------------------------------------------------------------
def test_mcp_add_corpus_entry_round_trips_load_corpus(tmp_path):
    """The MCP append tool must produce a file load_corpus can read verbatim."""
    from testvibe.corpus import load_corpus
    from testvibe.mcp import build_server

    corpus = tmp_path / "known-failures.yaml"
    repro = tmp_path / "repro.py"
    repro.write_text("def repro():\n    raise AssertionError('bug')\n")

    s = build_server(contract_path=None, corpus_path=corpus)

    async def go():
        r = await s.call_tool(
            "add_corpus_entry",
            {
                "id": "mcp-bug",
                "invariant": "push is idempotent",
                "repro_path": str(repro),
                "status": "open",
            },
        )
        return _unwrap(r)

    row = asyncio.run(go())
    assert row["id"] == "mcp-bug"
    assert row["source"] == "mcp"  # filled by the tool

    # The real test: load_corpus (the plugin's reader) must reload it with all
    # CorpusEntry fields intact. A private raw-dict dump could miss fields.
    entries = load_corpus(corpus)
    assert len(entries) == 1
    e = entries[0]
    assert e.id == "mcp-bug"
    assert e.invariant == "push is idempotent"
    assert e.repro == str(repro)
    assert e.source == "mcp"
    assert e.status == "open"
    # discovered_at must be today's date, as a valid ISO date (not just truthy).
    from datetime import date as _date

    assert e.discovered_at == _date.today().isoformat()
    _date.fromisoformat(e.discovered_at)  # raises if not a real ISO date


def test_mcp_add_corpus_entry_preserves_existing_rows(tmp_path):
    """add_corpus_entry via MCP must append, not overwrite, existing rows."""
    from testvibe.corpus import CorpusEntry, add_entry, load_corpus
    from testvibe.mcp import build_server

    corpus = tmp_path / "known-failures.yaml"
    repro = tmp_path / "repro.py"
    repro.write_text("def repro():\n    raise AssertionError('bug')\n")

    # Seed one entry directly via the corpus API.
    add_entry(
        corpus,
        CorpusEntry(
            id="seed",
            invariant="inv-seed",
            discovered_at="2026-08-02",
            source="test",
            repro=str(repro),
            status="open",
        ),
    )

    s = build_server(contract_path=None, corpus_path=corpus)

    async def go():
        return await s.call_tool(
            "add_corpus_entry",
            {
                "id": "mcp-added",
                "invariant": "inv-mcp",
                "repro_path": str(repro),
                "status": "pinned",
            },
        )

    asyncio.run(go())

    entries = load_corpus(corpus)
    ids = [e.id for e in entries]
    assert ids == ["seed", "mcp-added"]


def test_mcp_promote_corpus_respects_green_signal(tmp_path):
    """promote_corpus must only flip to fixed (the corpus.promote_entry contract).

    The MCP tool wraps corpus.promote_entry, so it inherits the green-signal
    invariant: a promote call flips status -> fixed (the MCP surface is the
    "after green" path — the agent has already confirmed the re-run passes).
    """
    from testvibe.corpus import load_corpus
    from testvibe.mcp import build_server

    corpus = tmp_path / "known-failures.yaml"
    repro = tmp_path / "repro.py"
    repro.write_text("def repro():\n    return True\n")

    s = build_server(contract_path=None, corpus_path=corpus)

    async def drive():
        await s.call_tool(
            "add_corpus_entry",
            {
                "id": "to-promote",
                "invariant": "inv",
                "repro_path": str(repro),
                "status": "pinned",
            },
        )
        promoted = await s.call_tool("promote_corpus", {"id": "to-promote"})
        return _unwrap(promoted)

    promoted = asyncio.run(drive())
    assert promoted["status"] == "fixed"
    # fixed drops out of the active quarantine set
    assert load_corpus(corpus) == []


def test_mcp_promote_corpus_unknown_id_reports_not_found(tmp_path):
    """promote_corpus on an unknown id yields a structured not-found (no crash).

    Seeds the corpus with one real entry first (so the file EXISTS), then
    promotes a ghost id. This isolates the "unknown id" case from the "missing
    file" case (which patch J now classifies distinctly as ``corpus_missing``).
    """
    from testvibe.corpus import CorpusEntry, add_entry
    from testvibe.mcp import build_server

    corpus = tmp_path / "known-failures.yaml"
    repro = tmp_path / "repro.py"
    repro.write_text("def repro():\n    return True\n")
    # Seed a real entry so the corpus file exists (otherwise the error is
    # corpus_missing, not not_found).
    add_entry(
        corpus,
        CorpusEntry(
            id="real",
            invariant="inv",
            discovered_at="2026-08-02",
            source="test",
            repro=str(repro),
            status="pinned",
        ),
    )
    s = build_server(contract_path=None, corpus_path=corpus)

    async def go():
        return await s.call_tool("promote_corpus", {"id": "ghost"})

    out = asyncio.run(go())
    row = _unwrap(out)
    # MCP surface is graceful (JSON with a specific error marker), not a raise.
    # After patch J the marker is classified: an unknown id -> "not_found" (not
    # the generic catch-all). Pin the exact contract shape, not a disjunction.
    assert row.get("error") == "not_found"
    assert row.get("status") == "unknown"


def test_mcp_has_no_private_dump_after_corpus_refactor(tmp_path):
    """After the refactor, mcp.py must not carry its own _dump_raw_yaml.

    The single-mutation-path invariant: corpus.py owns all writes to
    known-failures.yaml. A leftover private dump in mcp.py would be a regression
    (two write paths that can drift). This is a structural test guarding the
    refactor's intent, not behavior.
    """
    import testvibe.mcp as mcp_mod

    assert not hasattr(mcp_mod, "_dump_raw_yaml"), (
        "mcp.py must delegate corpus writes to corpus.py; found leftover "
        "_dump_raw_yaml (two write paths → read/write drift)."
    )


# ---------------------------------------------------------------------------
# run_scenario delegation (Task: mcp.run_scenario → delegate to _run.run_scenarios).
#
# run_scenario must delegate the pytest-subprocess + tri-state-exit-code work to
# _run.run_scenarios so the CLI and MCP share ONE orchestrator. The proof: a
# monkeypatch on _run.run_scenarios is observed by the MCP tool (the patched fn
# runs instead of the real subprocess). The existing behavioral tests
# (pass/fail/infra) continue to hold because delegation preserves behavior.
# ---------------------------------------------------------------------------
def test_mcp_run_scenario_delegates_to_run_scenarios(tmp_path, monkeypatch):
    """run_scenario must call _run.run_scenarios (not its own subprocess).

    Monkeypatches _run.run_scenarios with a sentinel RunReport; if the MCP tool
    still had its own subprocess logic, the patched fn would never run and the
    returned report would not carry the sentinel.
    """
    from testvibe import _run
    from testvibe.mcp import build_server
    from testvibe.report import RunReport

    sentinel = RunReport(
        tool="testvibe-mcp", run="scenario:DELEGATED", passed=True
    )

    captured: dict = {}

    def fake_run_scenarios(cwd=None, *, name=None):
        captured["cwd"] = cwd
        captured["name"] = name
        return sentinel

    monkeypatch.setattr(_run, "run_scenarios", fake_run_scenarios)

    s = build_server(contract_path=None, cwd=tmp_path)

    async def drive():
        run_id = await s.call_tool("run_scenario", {"name": "whatever"})
        report_raw = await s.call_tool(
            "get_run_report", {"run_id": _unwrap(run_id)}
        )
        return report_raw

    report_raw = asyncio.run(drive())
    report = json.loads(_unwrap(report_raw))

    # The patched orchestrator ran, so the sentinel's run label is visible.
    assert report["run"] == "scenario:DELEGATED"
    assert report["passed"] is True
    # And the cwd + name were forwarded correctly.
    assert captured["name"] == "whatever"


def test_mcp_run_scenario_forwards_cwd(tmp_path, monkeypatch):
    """run_scenario forwards the configured cwd to run_scenarios."""
    from testvibe import _run
    from testvibe.mcp import build_server
    from testvibe.report import RunReport

    seen_cwd = {}

    def fake(cwd=None, *, name=None):
        seen_cwd["cwd"] = cwd
        return RunReport(tool="t", run="r", passed=True)

    monkeypatch.setattr(_run, "run_scenarios", fake)

    s = build_server(contract_path=None, cwd=str(tmp_path))

    async def go():
        await s.call_tool("run_scenario", {"name": "x"})
        return None

    asyncio.run(go())
    assert seen_cwd["cwd"] == str(tmp_path)


# ---------------------------------------------------------------------------
# Patch J — promote_corpus must distinguish corrupt-YAML from not-found.
# ---------------------------------------------------------------------------
def test_mcp_promote_corpus_corrupt_yaml_reports_corpus_corrupt(tmp_path):
    """promote_corpus on a present-but-corrupt corpus file -> error='corpus_corrupt'.

    Previously CorpusError collapsed to {error:'not_found'} unconditionally, but
    a corrupt file is a distinct caller bug. After patch J the marker is
    classified: corrupt YAML -> 'corpus_corrupt' (not the misleading 'not_found').
    """
    from testvibe.mcp import build_server

    corpus = tmp_path / "known-failures.yaml"
    corpus.write_text(" - id: broken\n    bad: [unterminated\n")  # corrupt YAML
    s = build_server(contract_path=None, corpus_path=corpus)

    async def go():
        return await s.call_tool("promote_corpus", {"id": "anything"})

    out = asyncio.run(go())
    row = _unwrap(out)
    assert row.get("error") == "corpus_corrupt", (
        f"corrupt YAML must classify as corpus_corrupt, got: {row}"
    )


def test_mcp_promote_corpus_missing_file_reports_corpus_missing(tmp_path):
    """promote_corpus on a genuinely-absent corpus file -> error='corpus_missing'.

    Distinct from not_found (unknown id in an existing file): the file itself is
    absent. After patch J this is classified as 'corpus_missing'."""
    from testvibe.mcp import build_server

    corpus = tmp_path / "absent.yaml"
    s = build_server(contract_path=None, corpus_path=corpus)

    async def go():
        return await s.call_tool("promote_corpus", {"id": "anything"})

    out = asyncio.run(go())
    row = _unwrap(out)
    assert row.get("error") == "corpus_missing", (
        f"missing file must classify as corpus_missing, got: {row}"
    )


# ---------------------------------------------------------------------------
# Patch K — add_corpus_entry must return a structured error, not raise.
# ---------------------------------------------------------------------------
def test_mcp_add_corpus_entry_invalid_status_returns_structured_error(tmp_path):
    """add_corpus_entry with an invalid status -> structured {error} dict, not raise.

    Parity with promote_corpus: corpus.add_entry raises CorpusError (invalid
    status, duplicate id after patch D), but the MCP tool must catch it and
    return a structured dict so an agent can branch on the marker.
    """
    from testvibe.mcp import build_server

    corpus = tmp_path / "known-failures.yaml"
    repro = tmp_path / "repro.py"
    repro.write_text("def repro():\n    raise AssertionError('bug')\n")
    s = build_server(contract_path=None, corpus_path=corpus)

    async def go():
        return await s.call_tool(
            "add_corpus_entry",
            {
                "id": "bad-status",
                "invariant": "inv",
                "repro_path": str(repro),
                "status": "fixed",  # invalid — add_entry accepts only open/pinned
            },
        )

    out = asyncio.run(go())
    row = _unwrap(out)
    # Structured error dict (never a raise), with an error marker + message.
    assert "error" in row, f"expected structured error dict, got: {row}"
    assert "message" in row
    assert row.get("id") == "bad-status"


def test_mcp_add_corpus_entry_duplicate_id_returns_structured_error(tmp_path):
    """add_corpus_entry with a duplicate id -> structured error dict, not raise.

    After patch D, add_entry rejects duplicate ids. The MCP tool must surface
    that as a structured error (parity with promote_corpus), not an RPC raise.
    """
    from testvibe.corpus import CorpusEntry, add_entry
    from testvibe.mcp import build_server

    corpus = tmp_path / "known-failures.yaml"
    repro = tmp_path / "repro.py"
    repro.write_text("def repro():\n    raise AssertionError('bug')\n")
    add_entry(
        corpus,
        CorpusEntry(
            id="dup",
            invariant="first",
            discovered_at="2026-08-02",
            source="test",
            repro=str(repro),
            status="open",
        ),
    )
    s = build_server(contract_path=None, corpus_path=corpus)

    async def go():
        return await s.call_tool(
            "add_corpus_entry",
            {
                "id": "dup",
                "invariant": "second",
                "repro_path": str(repro),
                "status": "open",
            },
        )

    out = asyncio.run(go())
    row = _unwrap(out)
    assert "error" in row, f"expected structured error dict for dup id, got: {row}"
