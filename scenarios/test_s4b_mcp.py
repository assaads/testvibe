"""S4b self-dogfood scenario: MCP run_scenario -> get_run_report round-trip.

The recursion is the point: testvibe's MCP server drives ``pytest`` on a tiny
hermetic testvibe scenario, and we assert the JSON report reflects ``passed=True``.
This exercises ``mcp.build_server()`` in-process (no network) and the
``run_scenario``/``get_run_report`` tools through the real fastmcp transport.

The hermetic scenario project is laid down under ``tmp_path`` so the subprocess
pytest never touches a repo-collected path. ``run_scenario`` runs
``<sys.executable> -m pytest`` (the venv interpreter), so the subprocess uses
the same working testvibe install. Per the contract, exit code 1 is a product
failure and any other non-zero is infra; the passing case here exits 0.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from _helpers import _unwrap

from testvibe import scenario


def _write_hermetic_scenario_project(root: Path, name: str) -> None:
    """Lay down a one-scenario hermetic pytest project under ``root``.

    ``run_scenario`` selects via ``pytest -k <name>``, which matches the test
    *function name* (the nodeid), so the function name embeds the scenario name.
    """
    fn_name = "test_" + name
    (root / "conftest.py").write_text("import testvibe.plugin  # noqa: F401\n")
    (root / "test_demo.py").write_text(
        "from testvibe import scenario\n"
        "\n"
        f'@scenario("{name}")\n'
        f"def {fn_name}() -> None:\n"
        "    assert True  # hermetic passing scenario\n",
        encoding="utf-8",
    )


@scenario("s4b_mcp_run_scenario_roundtrip", kind="hermetic")
def test_s4b_mcp_run_scenario_roundtrip(tmp_path: Path) -> None:
    """run_scenario -> get_run_report returns JSON with passed=True."""
    fastmcp = pytest.importorskip("fastmcp")  # skip cleanly if fastmcp absent
    del fastmcp
    from testvibe.mcp import build_server

    _write_hermetic_scenario_project(tmp_path, "demo_s4b_pass")
    server = build_server(contract_path=None, cwd=tmp_path)

    async def drive() -> tuple[object, object]:
        run_id_raw = await server.call_tool(
            "run_scenario", {"name": "demo_s4b_pass"}
        )
        rid = _unwrap(run_id_raw)
        report_raw = await server.call_tool("get_run_report", {"run_id": rid})
        return rid, _unwrap(report_raw)

    run_id, report_raw = asyncio.run(drive())

    # run_scenario returns a run-id string with the documented prefix.
    assert isinstance(run_id, str)
    assert run_id.startswith("run-"), f"unexpected run_id: {run_id!r}"

    # The report is well-formed JSON with passed=True for the hermetic pass case.
    assert isinstance(report_raw, str), "get_run_report must return JSON text"
    report = json.loads(report_raw)
    assert report["passed"] is True, (
        f"hermetic passing scenario must report passed=True, got: {report}"
    )
    assert report["run"] == "scenario:demo_s4b_pass"
    # A passing run records no failures.
    assert report.get("failures") == [], (
        f"a passing run must record no failures, got: {report.get('failures')}"
    )


def test_s4b_mcp_infra_vs_product_classification(tmp_path: Path) -> None:
    """A collection error (exit != 1) is tagged infra; exit 1 is product.

    This pins the documented contract: ``run_scenario`` classifies pytest exit
    code 1 as a product failure and any other non-zero as infra. We exercise
    the infra path (a broken import -> exit 2) and assert the failure kind.
    """
    pytest.importorskip("fastmcp")
    from testvibe.mcp import build_server

    # A test module with a bad import fails at collection -> pytest exit 2 (infra).
    (tmp_path / "conftest.py").write_text("import testvibe.plugin  # noqa: F401\n")
    (tmp_path / "test_broken.py").write_text(
        "import does_not_exist_module_xyz\n"  # collection-time ImportError -> exit 2
        "from testvibe import scenario\n"
        "\n"
        '@scenario("demo_s4b_broken")\n'
        "def test_demo_s4b_broken() -> None:\n"
        "    assert True\n",
        encoding="utf-8",
    )
    server = build_server(contract_path=None, cwd=tmp_path)

    async def drive() -> object:
        run_id_raw = await server.call_tool(
            "run_scenario", {"name": "demo_s4b_broken"}
        )
        report_raw = await server.call_tool(
            "get_run_report", {"run_id": _unwrap(run_id_raw)}
        )
        return _unwrap(report_raw)

    report_raw = asyncio.run(drive())
    assert isinstance(report_raw, str), "get_run_report must return JSON text"
    report = json.loads(report_raw)
    # A collection error is infra, not a product regression.
    assert report["passed"] is False
    assert report["failures"], "expected a failure row for the broken scenario"
    assert report["failures"][0]["kind"] == "infra", (
        f"collection error (exit 2) must classify as infra, got: {report['failures'][0]}"
    )


def test_s4b_mcp_product_failure_classified_as_product(tmp_path: Path) -> None:
    """A failing scenario assertion (pytest exit 1) is tagged product.

    Companion to the infra test above: the documented contract classifies
    pytest exit code 1 as a product failure and any other non-zero as infra.
    The infra test covers the exit-!=1 branch; this test covers the exit-==1
    branch end-to-end through ``run_scenario`` so BOTH halves of the split are
    verified (a regression that flipped the comparison would be caught here).
    """
    pytest.importorskip("fastmcp")
    from testvibe.mcp import build_server

    # A scenario whose body asserts False -> pytest exit 1 (a product failure,
    # not a collection/runner error). ``run_scenario`` selects via -k on the
    # function name, which embeds the scenario name.
    (tmp_path / "conftest.py").write_text("import testvibe.plugin  # noqa: F401\n")
    (tmp_path / "test_fail.py").write_text(
        "from testvibe import scenario\n"
        "\n"
        '@scenario("demo_s4b_product_fail")\n'
        "def test_demo_s4b_product_fail() -> None:\n"
        "    assert False  # product assertion failure -> exit 1\n",
        encoding="utf-8",
    )
    server = build_server(contract_path=None, cwd=tmp_path)

    async def drive() -> object:
        run_id_raw = await server.call_tool(
            "run_scenario", {"name": "demo_s4b_product_fail"}
        )
        report_raw = await server.call_tool(
            "get_run_report", {"run_id": _unwrap(run_id_raw)}
        )
        return _unwrap(report_raw)

    report_raw = asyncio.run(drive())
    assert isinstance(report_raw, str), "get_run_report must return JSON text"
    report = json.loads(report_raw)
    assert report["passed"] is False
    assert report["failures"], "expected a failure row for the failing scenario"
    assert report["failures"][0]["kind"] == "product", (
        f"a scenario assertion failure (exit 1) must classify as product, "
        f"got: {report['failures'][0]}"
    )
