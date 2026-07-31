"""testvibe.mcp - FastMCP server exposing the testvibe engine to coding agents.

This is a thin, DATA-ONLY RPC layer (Task B4 / Spec S8). The server makes **no
LLM and no network calls** of its own; it wires the existing testvibe
primitives - the scenario runner, :class:`~testvibe.report.RunReport`, the
:mod:`testvibe.advisory` analyzer, and the captured-failure
:mod:`testvibe.corpus` - into six named tools a coding agent invokes to observe
runs, surface coverage gaps, and grow the quarantine corpus. All interpretation
of the returned rows stays with the agent.

``build_server(contract_path=None)`` constructs the server. ``contract_path=None``
uses ``./testvibe.yaml`` in the cwd if present, else an empty contract (empty
fixture/touched sets, no transcript) so the advisory tools simply return ``[]``
until the agent feeds them data, and the corpus path defaults to
``./known-failures.yaml``. Optional kwargs (``corpus_path``, ``fixture_paths``,
``touched_paths``, ``transcript``, ``baseline``, ``cwd``) override those
defaults so callers - and tests - can pin a deterministic surface without
depending on cwd state.

State (run reports + their advisory rows) is held in-process, keyed by the
``run_id`` that ``run_scenario`` returns.
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from fastmcp import FastMCP

from . import advisory
from .corpus import load_corpus
from .report import Failure, RunReport

__all__ = ["build_server"]


def _load_raw_yaml(path: Path) -> list[Any]:
    """Best-effort load of a corpus file as a raw list of mappings.

    Returns ``[]`` for a missing/empty/malformed file or anything that is not a
    top-level YAML list - the corpus tools append/promote against this shape, so
    a corrupt file degrades to an empty list rather than raising. (Strict
    validation of *entry* fields is :func:`testvibe.corpus.load_corpus`'s job;
    this loader only needs the raw rows.)
    """
    if not path.exists():
        return []
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError:
        return []
    if raw is None:
        return []
    if not isinstance(raw, list):
        return []
    return raw


def _dump_raw_yaml(path: Path, rows: list[Any]) -> None:
    """Persist corpus rows, creating the parent directory if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(rows, sort_keys=False, default_flow_style=False)
    )


def _adv_to_dict(a: advisory.Advisory) -> dict[str, str]:
    return {"kind": a.kind, "message": a.message, "detail": a.detail}


def build_server(
    contract_path: str | Path | None = None,
    *,
    corpus_path: str | Path | None = None,
    fixture_paths: list[str] | None = None,
    touched_paths: list[str] | None = None,
    transcript: str | None = None,
    baseline: float | None = None,
    cwd: str | Path | None = None,
) -> FastMCP:
    """Build a FastMCP server exposing the testvibe engine as six named tools.

    Tools exposed (names are the contract an agent depends on):

      * ``run_scenario(name)``          - run a testvibe scenario; return ``run_id``.
      * ``get_run_report(run_id)``      - the run's :class:`RunReport` as JSON.
      * ``list_coverage_gaps()``        - ``advisory.analyze`` ``coverage_gap`` rows.
      * ``list_advisories(run_id)``     - advisory rows recorded for a run.
      * ``add_corpus_entry(...)``       - append a captured failure to the corpus.
      * ``promote_corpus(id)``          - flip a corpus entry to ``status: fixed``.

    Parameters
    ----------
    contract_path:
        Path to a ``testvibe.yaml`` contract. ``None`` (default) uses
        ``./testvibe.yaml`` in the cwd if present, else an empty contract (empty
        fixture/touched sets, no transcript) so the advisory tools return ``[]``
        until the agent feeds them data. If a path is given and exists, it is
        parsed (best-effort) for
        ``fixture_paths``/``touched_paths``/``transcript``/``baseline`` defaults.
    corpus_path:
        Path to ``known-failures.yaml``. Defaults to ``./known-failures.yaml``
        (cwd) when not given. The corpus tools read/append this file.
    fixture_paths / touched_paths / transcript / baseline:
        Optional overrides feeding :func:`testvibe.advisory.analyze`. Explicit
        kwargs take precedence over values pulled from the contract.
    cwd:
        Working directory for the pytest subprocess invoked by
        ``run_scenario``. Defaults to the current working directory.
    """
    m = FastMCP("testvibe")

    # ---- configuration -----------------------------------------------------
    contract = _load_contract(contract_path)

    cfg_cwd = str(cwd) if cwd is not None else None
    cfg_corpus = (
        Path(corpus_path)
        if corpus_path is not None
        else Path("known-failures.yaml")
    )
    cfg_fixtures = _coerce_str_list(fixture_paths, contract, "fixture_paths")
    cfg_touched = _coerce_str_list(touched_paths, contract, "touched_paths")
    cfg_transcript = transcript if transcript is not None else (
        contract.get("transcript") or ""
    )
    if baseline is None:
        contract_baseline = contract.get("baseline")
        cfg_baseline = (
            float(contract_baseline) if contract_baseline is not None else None
        )
    else:
        cfg_baseline = float(baseline)

    # ---- in-process run state ---------------------------------------------
    _runs: dict[str, RunReport] = {}
    _run_advisories: dict[str, list[dict[str, str]]] = {}

    # ---- tools -------------------------------------------------------------

    @m.tool()
    def run_scenario(name: str) -> str:
        """Invoke pytest on a testvibe scenario and return its ``run_id``.

        Runs ``pytest -m testvibe_scenario -k <name>`` as a subprocess in the
        configured cwd, captures pass/fail + output, and stores a
        :class:`RunReport` keyed by the returned ``run_id``. Use
        ``get_run_report`` / ``list_advisories`` with that id to inspect it.
        """
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "-m",
            "testvibe_scenario",
            "-k",
            str(name),
            "-q",
        ]
        passed = False
        # ``infra`` separates runner/environment failures from genuine product
        # regressions (PLAYBOOK infra-vs-product taxonomy). A pytest exit code
        # of 1 means a scenario assertion failed -> product. Any other non-zero
        # code (2 collection error, 3 internal error, 4 usage, 5 no tests
        # collected) or a subprocess exception is the harness/environment
        # misbehaving -> infra, not a product bug.
        # ``sys.executable -m pytest`` never raises FileNotFoundError (the
        # interpreter always exists; a missing pytest module makes the python
        # invocation exit non-zero with a stderr message instead), so there is
        # no FileNotFoundError branch to handle here.
        infra = False
        stdout = ""
        stderr = ""
        try:
            proc = subprocess.run(
                cmd,
                cwd=cfg_cwd,
                capture_output=True,
                text=True,
                timeout=600,
            )
            passed = proc.returncode == 0
            if not passed and proc.returncode != 1:
                infra = True
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
        except subprocess.TimeoutExpired as exc:
            infra = True
            stderr = "scenario run timed out"
            stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""

        report = RunReport(
            tool="testvibe-mcp", run=f"scenario:{name}", passed=passed
        )
        combined = (stdout + "\n" + stderr).strip()
        if not passed:
            report.add_failure(
                Failure(
                    kind="infra" if infra else "product",
                    message=(
                        f"scenario '{name}' runner failed (infra)"
                        if infra
                        else f"scenario '{name}' did not pass"
                    ),
                    detail=combined[-4000:] if combined else "no output captured",
                )
            )

        # Feed the run output through the advisory analyzer so the agent gets
        # smell/coverage signals alongside the pass/fail verdict. ``report=[]``
        # because the op-level p90 records live elsewhere; here we only want the
        # transcript/coverage branches of analyze().
        adv_rows = advisory.analyze(
            report=[],
            baseline=cfg_baseline,
            fixture_paths=cfg_fixtures,
            touched_paths=cfg_touched,
            transcript=combined,
        )
        _runs[run_id] = report
        _run_advisories[run_id] = [_adv_to_dict(a) for a in adv_rows]
        return run_id

    @m.tool()
    def get_run_report(run_id: str) -> str:
        """Return the stored :class:`RunReport` for ``run_id`` as JSON.

        An unknown ``run_id`` yields a JSON object with an ``error`` marker
        rather than raising, so an agent can branch on it cleanly.
        """
        report = _runs.get(run_id)
        if report is None:
            return json.dumps(
                {"run_id": run_id, "error": "unknown run_id"}
            )
        return report.to_json()

    @m.tool()
    def list_coverage_gaps() -> list[dict[str, str]]:
        """Return ``coverage_gap`` advisory rows.

        A coverage gap is a path touched by dogfood/canary traces but absent
        from the configured fixture set - the data the agent turns into new
        scenarios. No LLM, no network: pure set difference via
        :func:`testvibe.advisory.analyze`.
        """
        rows = advisory.analyze(
            report=[],
            baseline=None,
            fixture_paths=cfg_fixtures,
            touched_paths=cfg_touched,
            transcript="",
        )
        return [_adv_to_dict(a) for a in rows if a.kind == "coverage_gap"]

    @m.tool()
    def list_advisories(run_id: str) -> list[dict[str, str]]:
        """Return the advisory rows recorded for ``run_id`` (``[]`` if unknown)."""
        return list(_run_advisories.get(run_id, []))

    @m.tool()
    def add_corpus_entry(
        id: str, invariant: str, repro_path: str, status: str = "open"
    ) -> dict[str, str]:
        """Append a captured failure to ``known-failures.yaml``.

        ``discovered_at`` (today) and ``source="mcp"`` are filled so the row
        satisfies :class:`testvibe.corpus.CorpusEntry`'s required fields and is
        immediately picked up by the plugin's quarantine collection hook.
        """
        entry = {
            "id": id,
            "invariant": invariant,
            "discovered_at": date.today().isoformat(),
            "source": "mcp",
            "repro": repro_path,
            "status": status,
        }
        rows = _load_raw_yaml(cfg_corpus)
        rows.append(entry)
        _dump_raw_yaml(cfg_corpus, rows)
        return entry

    @m.tool()
    def promote_corpus(id: str) -> dict[str, str]:
        """Flip a corpus entry to ``status: fixed`` and drop its xfail pin.

        Promotion works by writing ``status: fixed``; because
        :func:`testvibe.corpus.load_corpus` only collects ``open``/``pinned``
        entries, a fixed entry naturally drops out of the xfail quarantine set -
        no separate "delete xfail" step is needed.
        """
        rows = _load_raw_yaml(cfg_corpus)
        updated: dict[str, str] | None = None
        for row in rows:
            if isinstance(row, dict) and row.get("id") == id:
                row["status"] = "fixed"
                updated = row
        if updated is None:
            return {"id": id, "status": "unknown", "error": "not_found"}
        _dump_raw_yaml(cfg_corpus, rows)
        return updated

    return m


# ----------------------------------------------------------------------
# contract helpers (module-level; pure, no FastMCP dependency)
# ----------------------------------------------------------------------


def _load_contract(contract_path: str | Path | None) -> dict[str, Any]:
    """Best-effort parse of a ``testvibe.yaml`` contract for advisory defaults.

    ``contract_path=None`` falls back to ``./testvibe.yaml`` when present, else
    a no-op empty dict. A missing/malformed/non-mapping file degrades to ``{}``
    so the server always builds.
    """
    p = Path(contract_path) if contract_path is not None else Path("testvibe.yaml")
    if not p.exists():
        return {}
    try:
        data = yaml.safe_load(p.read_text())
    except yaml.YAMLError:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _coerce_str_list(
    explicit: list[str] | None,
    contract: dict[str, Any],
    key: str,
) -> list[str]:
    """Pick the explicit list, else the contract's list for ``key``, else ``[]``."""
    if explicit is not None:
        return [str(x) for x in explicit]
    raw = contract.get(key)
    if isinstance(raw, list):
        return [str(x) for x in raw]
    return []
